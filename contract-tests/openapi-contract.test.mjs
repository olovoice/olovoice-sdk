import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const contractDir = dirname(fileURLToPath(import.meta.url));

function readSpec(name) {
  const raw = readFileSync(resolve(contractDir, name), "utf8");
  return { raw, value: JSON.parse(raw) };
}

const english = readSpec("openapi.json");
const turkish = readSpec("openapi.tr.json");

function visit(value, callback, path = "$") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => visit(item, callback, `${path}[${index}]`));
    return;
  }
  if (value === null || typeof value !== "object") return;
  callback(value, path);
  for (const [key, item] of Object.entries(value)) {
    visit(item, callback, `${path}.${key}`);
  }
}

function resolvePointer(root, pointer) {
  assert.match(pointer, /^#\//, `Only internal refs are supported: ${pointer}`);
  return pointer
    .slice(2)
    .split("/")
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
    .reduce((value, part) => value?.[part], root);
}

function withoutProse(value) {
  if (Array.isArray(value)) return value.map(withoutProse);
  if (value === null || typeof value !== "object") return value;
  const omitted = new Set(["description", "summary", "title", "example", "examples"]);
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !omitted.has(key))
      .map(([key, item]) => [key, withoutProse(item)]),
  );
}

function valueHasType(value, expected) {
  if (expected === "null") return value === null;
  if (expected === "array") return Array.isArray(value);
  if (expected === "object") {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  if (expected === "integer") return Number.isInteger(value);
  if (expected === "number") return typeof value === "number" && Number.isFinite(value);
  return typeof value === expected;
}

function schemaErrors(value, schema, root, path = "$") {
  if (schema === true || schema === undefined) return [];
  if (schema === false) return [`${path}: false schema`];

  let errors = [];
  if (schema.$ref) {
    errors.push(...schemaErrors(value, resolvePointer(root, schema.$ref), root, path));
  }

  if (schema.allOf) {
    for (const part of schema.allOf) errors.push(...schemaErrors(value, part, root, path));
  }
  if (schema.anyOf) {
    const matches = schema.anyOf.filter(
      (part) => schemaErrors(value, part, root, path).length === 0,
    );
    if (matches.length === 0) errors.push(`${path}: no anyOf branch matched`);
  }
  if (schema.oneOf) {
    const matches = schema.oneOf.filter(
      (part) => schemaErrors(value, part, root, path).length === 0,
    );
    if (matches.length !== 1) errors.push(`${path}: expected one oneOf match, got ${matches.length}`);
  }
  if (schema.not && schemaErrors(value, schema.not, root, path).length === 0) {
    errors.push(`${path}: matched forbidden schema`);
  }
  if (schema.if && schemaErrors(value, schema.if, root, path).length === 0 && schema.then) {
    errors.push(...schemaErrors(value, schema.then, root, path));
  }

  if (Object.hasOwn(schema, "const") && JSON.stringify(value) !== JSON.stringify(schema.const)) {
    errors.push(`${path}: does not equal const`);
  }
  if (schema.enum && !schema.enum.some((item) => JSON.stringify(item) === JSON.stringify(value))) {
    errors.push(`${path}: not in enum`);
  }

  const types = schema.type === undefined ? [] : [schema.type].flat();
  if (types.length > 0 && !types.some((type) => valueHasType(value, type))) {
    errors.push(`${path}: expected ${types.join("|")}`);
    return errors;
  }

  const isObject = valueHasType(value, "object");
  if (isObject) {
    if (
      schema.minProperties !== undefined &&
      Object.keys(value).length < schema.minProperties
    ) {
      errors.push(`${path}: fewer than minProperties`);
    }
    for (const required of schema.required ?? []) {
      if (!Object.hasOwn(value, required)) errors.push(`${path}.${required}: required`);
    }
    for (const [key, propertySchema] of Object.entries(schema.properties ?? {})) {
      if (Object.hasOwn(value, key)) {
        errors.push(...schemaErrors(value[key], propertySchema, root, `${path}.${key}`));
      }
    }
    if (schema.additionalProperties === false) {
      const known = new Set(Object.keys(schema.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!known.has(key)) errors.push(`${path}.${key}: additional property`);
      }
    }
  }

  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => {
      errors.push(...schemaErrors(item, schema.items, root, `${path}[${index}]`));
    });
  }
  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) {
      errors.push(`${path}: shorter than minLength`);
    }
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) {
      errors.push(`${path}: pattern mismatch`);
    }
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path}: below minimum`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path}: above maximum`);
  }
  return errors;
}

function assertValid(value, schema, root = english.value) {
  assert.deepEqual(schemaErrors(value, schema, root), []);
}

function assertInvalid(value, schema, root = english.value) {
  assert.notDeepEqual(schemaErrors(value, schema, root), []);
}

test("all EN/TR internal refs resolve", () => {
  for (const [locale, spec] of [["en", english.value], ["tr", turkish.value]]) {
    const refs = [];
    visit(spec, (node, path) => {
      if (typeof node.$ref === "string") refs.push([node.$ref, path]);
    });
    assert.ok(refs.length > 0, `${locale}: expected internal refs`);
    for (const [ref, path] of refs) {
      assert.notEqual(resolvePointer(spec, ref), undefined, `${locale}: ${ref} at ${path}`);
    }
  }
});

test("EN/TR public contract structures stay in parity", () => {
  const project = (spec) => withoutProse({
    paths: spec.paths,
    security: spec.security,
    components: spec.components,
  });
  assert.deepEqual(project(turkish.value), project(english.value));
});

test("workspace Mintlify sources and vendored snapshots cannot drift", (context) => {
  const mintlifyDir = resolve(contractDir, "../../mintlify");
  if (!existsSync(resolve(mintlifyDir, "openapi.json"))) {
    context.skip("standalone SDK checkout: canonical Mintlify directory is absent");
    return;
  }
  for (const [name, snapshot] of [["openapi.json", english], ["openapi.tr.json", turkish]]) {
    const canonicalRaw = readFileSync(resolve(mintlifyDir, name), "utf8");
    assert.equal(snapshot.raw, canonicalRaw, `${name}: run npm run sync`);
    assert.deepEqual(snapshot.value, JSON.parse(canonicalRaw));
  }
});

test("operation scopes and web-call rollout metadata are explicit", () => {
  const expected = {
    "POST /call": ["calls:create"],
    "POST /web-call": ["web_calls:create"],
    "GET /call-logs": ["call_logs:read"],
    "GET /call-logs/{callId}": ["call_logs:read"],
    "GET /call-logs/{callId}/recording-url": ["recordings:read"],
    "GET /assistants": ["assistants:read"],
    "POST /assistants": ["assistants:write"],
    "GET /assistants/{assistantId}": ["assistants:read"],
    "PATCH /assistants/{assistantId}": ["assistants:write"],
    "DELETE /assistants/{assistantId}": ["assistants:write"],
    "POST /leads": ["leads:write"],
    "GET /metrics": ["metrics:read"],
  };
  for (const [operation, scopes] of Object.entries(expected)) {
    const [method, path] = operation.split(" ");
    assert.deepEqual(english.value.paths[path][method.toLowerCase()]["x-required-scopes"], scopes);
  }
  assert.deepEqual(english.value.paths["/web-call"].post["x-rollout"], {
    enabledByDefault: false,
    featureFlag: "PUBLIC_WEB_CALL_ENABLED",
    disabledStatus: 403,
    disabledCode: "web_call_disabled",
  });
});

test("/call selector and audio fixtures match runtime resolution", () => {
  const schema = english.value.paths["/call"].post.requestBody.content["application/json"].schema;
  assert.deepEqual(schema.required, ["phoneNumberId", "customer", "llm", "conversation", "backgroundAudio"]);

  const classic = {
    assistantId: "ast_1",
    phoneNumberId: "pn_1",
    customer: { number: "+905551234567" },
    firstMessage: "Hello",
    content: "Be helpful",
    llm: { provider: "openai", model: "gpt-4o" },
    tts: {
      provider: "elevenlabs",
      model: "eleven_turbo_v2_5",
      voiceId: "EXAVITQu4vr4xnSDxMaL",
    },
    stt: { language: "tr" },
    conversation: {},
    backgroundAudio: {},
  };
  assertValid(classic, schema);
  assertValid({ ...classic, squadId: "squad_1" }, schema); // at least one, not XOR
  const squad = { ...classic, squadId: "squad_1" };
  delete squad.assistantId;
  delete squad.firstMessage;
  delete squad.content;
  assertValid(squad, schema); // saved graph may hydrate prompts

  const halfCascade = {
    ...classic,
    llm: { provider: "openai-realtime", model: "gpt-realtime" },
  };
  delete halfCascade.stt;
  assertValid(halfCascade, schema); // omitted mode normalizes to halfCascade

  const nativeAudio = {
    ...classic,
    llm: { provider: "openai", model: "gpt-realtime", realtimeMode: "nativeAudio" },
  };
  delete nativeAudio.tts;
  delete nativeAudio.stt;
  assertValid(nativeAudio, schema);

  const missingPrompt = { ...classic };
  delete missingPrompt.firstMessage;
  assertInvalid(missingPrompt, schema);
  const noSelector = { ...classic };
  delete noSelector.assistantId;
  assertInvalid(noSelector, schema);
  const classicWithoutAudio = { ...classic };
  delete classicWithoutAudio.tts;
  delete classicWithoutAudio.stt;
  assertInvalid(classicWithoutAudio, schema);
  assertInvalid({ ...classic, llm: {} }, schema);
  assertInvalid({ ...classic, tts: {} }, schema);
  assertInvalid({ ...halfCascade, llm: { provider: "openai-realtime" } }, schema);
});

test("runtime provider enums and dispatch-critical fields reject worker failures early", () => {
  const schemas = english.value.components.schemas;
  const llmProviders = [
    "openai", "openai-realtime", "openai_realtime", "openai.realtime",
    "google", "gemini", "anthropic", "aws", "amazon", "bedrock",
    "groq", "groq.ai", "groqai", "qwen",
  ];
  const ttsProviders = [
    "aws", "amazon", "elevenlabs", "eleven", "freya", "freyavoice",
    "nova", "novaforge", "nova-tts", "openai", "polly",
  ];
  const sttProviders = [
    "azure", "azure_speech", "azure-speech", "aws", "amazon", "transcribe",
    "transcribe-streaming", "deepgram", "dg", "elevenlabs", "eleven",
    "eleven-labs", "freya", "freyavoice", "groq", "groq.ai", "groqai",
    "nova", "novaforge", "nova-stt", "openai", "whisper",
  ];

  assert.deepEqual(schemas.RuntimeLlmConfig.properties.provider.enum, llmProviders);
  assert.deepEqual(schemas.RuntimeLlmConfig.required, ["provider", "model"]);
  for (const provider of llmProviders) {
    assertValid({ provider, model: "supported-model" }, schemas.RuntimeLlmConfig);
  }
  assertInvalid({ provider: "unknown", model: "model" }, schemas.RuntimeLlmConfig);
  assertInvalid({ provider: "openai" }, schemas.RuntimeLlmConfig);

  assert.deepEqual(schemas.RuntimeTtsConfig.properties.provider.enum, ttsProviders);
  assert.deepEqual(schemas.RuntimeTtsConfig.required, ["provider"]);
  for (const provider of ["elevenlabs", "eleven", "openai"]) {
    assertValid({ provider, model: "supported-model", voiceId: "voice_1" }, schemas.RuntimeTtsConfig);
  }
  for (const provider of ["aws", "amazon", "polly"]) {
    assertValid({ provider, voiceId: "voice_1" }, schemas.RuntimeTtsConfig);
    assertValid({ provider, model: null, voiceId: "voice_1" }, schemas.RuntimeTtsConfig);
  }
  for (const provider of ["freya", "freyavoice", "nova", "novaforge", "nova-tts"]) {
    assertValid({ provider }, schemas.RuntimeTtsConfig);
  }
  assertInvalid(
    { provider: "elevenlabs", voiceId: "voice_1" },
    schemas.RuntimeTtsConfig,
  );
  assertInvalid(
    { provider: "elevenlabs", model: "eleven_turbo_v2_5" },
    schemas.RuntimeTtsConfig,
  );
  assertInvalid(
    { provider: "unknown", model: "model", voiceId: "voice_1" },
    schemas.RuntimeTtsConfig,
  );
  assertValid(
    { provider: "aws", model: "polly-neural", voiceId: "Joanna" },
    schemas.RuntimeTtsConfig,
  );
  assertInvalid(
    { provider: "aws", model: "polly-neural" },
    schemas.RuntimeTtsConfig,
  );
  assertInvalid(
    { provider: "amazon", model: "bogus-aws-model", voiceId: "Joanna" },
    schemas.RuntimeTtsConfig,
  );

  assert.deepEqual(schemas.RuntimeSttConfig.properties.provider.enum, sttProviders);
  assertValid({ language: "tr" }, schemas.RuntimeSttConfig);
  for (const provider of sttProviders) {
    assertValid({ provider }, schemas.RuntimeSttConfig);
  }
  assertInvalid({ provider: "unknown" }, schemas.RuntimeSttConfig);
});

test("assistant PATCH requires a field and models explicit null clears", () => {
  const schema = english.value.paths["/assistants/{assistantId}"].patch
    .requestBody.content["application/json"].schema;
  assert.equal(schema.minProperties, 1);
  assertInvalid({}, schema);
  assertValid({ firstMessage: null }, schema);
  assertValid({ content: null }, schema);
  assertValid({ serverUrl: null }, schema);
  assertValid(
    { firstMessage: null, content: null, serverUrl: null },
    schema,
  );
  assertInvalid({ firstMessage: 1 }, schema);
  assertInvalid({ content: false }, schema);
  assertInvalid({ serverUrl: [] }, schema);
});

test("metrics 200 response references and validates the concrete aggregate shape", () => {
  const response = english.value.paths["/metrics"].get.responses["200"]
    .content["application/json"];
  assert.equal(response.schema.$ref, "#/components/schemas/MetricsResponse");
  assertValid(response.example, response.schema);
  assert.deepEqual(english.value.components.schemas.MetricsResponse.required, [
    "summary",
    "trends",
    "hourlyActivity",
    "durationDistribution",
    "disconnectReasons",
    "sentimentAnalysis",
    "funnel",
    "topAssistants",
    "toolUsage",
  ]);

  const nullableCurrency = structuredClone(response.example);
  nullableCurrency.summary.currency = null;
  assertValid(nullableCurrency, response.schema);

  const missingToolUsage = structuredClone(response.example);
  delete missingToolUsage.toolUsage;
  assertInvalid(missingToolUsage, response.schema);

  const unknownTopLevel = { ...response.example, timeline: [] };
  assertInvalid(unknownTopLevel, response.schema);
});

test("web-call hydrates minimal selectors but rejects server-owned fields", () => {
  const schema = english.value.paths["/web-call"].post.requestBody.content["application/json"].schema;
  const minimal = { organizationId: "org_1", assistantId: "ast_1" };
  assertValid(minimal, schema);
  for (const key of ["costs", "costConfig", "cost_config", "costCurrency", "webParticipantJoinTimeoutSeconds"]) {
    assertInvalid({ ...minimal, [key]: {} }, schema);
  }

  const response = english.value.paths["/web-call"].post.responses["200"]
    .content["application/json"];
  assert.equal(response.schema.$ref, "#/components/schemas/WebCallResponse");
  assertValid(response.example, response.schema);
  assert.equal(response.example.connectionUrl, "wss://rtc.olovoice.ai");
  assert.deepEqual(
    english.value.components.schemas.WebCallResponse.required,
    [
      "success",
      "callId",
      "roomName",
      "token",
      "connectionUrl",
      "expiresInSeconds",
      "startedAt",
      "subscriptionLimits",
    ],
  );

  const providerName = ["live", "kit"].join("");
  assert.doesNotMatch(english.raw, new RegExp(providerName, "i"));
  assert.doesNotMatch(turkish.raw, new RegExp(providerName, "i"));
});

test("carrier pass-through and assistant fallback responses stay modeled", () => {
  const schemas = english.value.components.schemas;
  const response = {
    success: true,
    subscriptionLimits: { concurrencyBlocked: false, concurrencyLimit: 10, remainingConcurrentCalls: 9 },
    payload: {
      callId: "call_1",
      assistantId: "ast_1",
      phoneNumberId: "pn_1",
      customer: { number: "+905551234567" },
      organizationId: "org_1",
      requestId: "req_1",
    },
    carrier: { ok: true },
  };
  for (const carrier of [{ ok: true }, { skipped: true, reason: "duplicate" }, "accepted", null, true, ["ok"]]) {
    assertValid({ ...response, carrier }, schemas.CreateCallResponse);
  }
  assert.ok(!schemas.CarrierResponse.oneOf[0].required?.includes("callId"));
  assertValid({ success: true, assistantId: "ast_1", warning: "read-back failed" }, schemas.CreateAssistantResponse);
  assertValid({ success: true, warning: "read-back failed" }, schemas.UpdateAssistantResponse);
});

test("assistant persistence inputs reject lossy keyword and thinking-string shapes", () => {
  const schemas = english.value.components.schemas;
  assertValid({ provider: "deepgram", keywords: [{ phrase: "olovoice", boost: 2 }] }, schemas.AssistantSttSettingsInput);
  assertValid({ provider: "deepgram", keywords: [{ phrase: "olovoice" }] }, schemas.AssistantSttSettingsInput);
  assertInvalid({ keywords: [{ phrase: "olovoice", boost: 2 }] }, schemas.AssistantSttSettingsInput);
  assertInvalid({ provider: "deepgram", keywords: ["olovoice"] }, schemas.AssistantSttSettingsInput);
  assert.equal(schemas.AssistantSttSettings.properties.keywordBoosts, undefined);
  assertValid({ ambient: "office", thinking: { builtin: "keyboard", volume: 0.2 } }, schemas.AssistantBackgroundAudioInput);
  assertInvalid({ thinking: "keyboard" }, schemas.AssistantBackgroundAudioInput);
});

test("call-log detail nullability and persisted core fields stay distinct", () => {
  const schemas = english.value.components.schemas;
  const callLog = schemas.CallLog;
  for (const key of ["callId", "callType", "status", "startedAt", "createdAt", "updatedAt"]) {
    assert.equal(callLog.properties[key].type, "string", `CallLog.${key}`);
    assert.ok(callLog.required.includes(key), `CallLog.${key} required`);
  }
  for (const key of ["timeline", "toolRuns", "structuredOutputs", "metadata", "publicPayload"]) {
    assert.ok(callLog.properties[key].type.includes("null"), `CallLog.${key} nullable`);
  }
  assert.equal(callLog.properties.payload.type, "null");
  for (const key of ["status", "createdAt", "updatedAt"]) {
    assert.equal(schemas.Assistant.properties[key].type, "string", `Assistant.${key}`);
    assert.ok(schemas.Assistant.required.includes(key), `Assistant.${key} required`);
  }
});

test("pre-release tooling baseline is Node 22 and Python 3.11", () => {
  const packageJson = JSON.parse(
    readFileSync(resolve(contractDir, "package.json"), "utf8"),
  );
  assert.equal(packageJson.engines.node, ">=22");
  assert.match(
    readFileSync(resolve(contractDir, "README.md"), "utf8"),
    /Node 22\+/,
  );

  const sdkDir = resolve(contractDir, "..");
  assert.match(
    readFileSync(resolve(sdkDir, "README.md"), "utf8"),
    /Node 22\+/,
  );
  assert.match(
    readFileSync(resolve(sdkDir, "python/pyproject.toml"), "utf8"),
    /requires-python = ">=3\.11"/,
  );
});

test("Mintlify does not expose unpublished SDK preview pages", (context) => {
  const docsPath = resolve(contractDir, "../../mintlify/docs.json");
  if (!existsSync(docsPath)) {
    context.skip("standalone SDK checkout: Mintlify navigation is absent");
    return;
  }
  const docs = JSON.parse(readFileSync(docsPath, "utf8"));
  const pages = docs.navigation.languages.flatMap((language) =>
    language.groups.flatMap((group) => group.pages ?? []),
  );
  const unpublishedPages = [
    "en/sdk-typescript",
    "en/sdk-python",
    "tr/sdk-typescript",
    "tr/sdk-python",
  ];
  for (const page of unpublishedPages) {
    assert.ok(
      !pages.includes(page),
      `${page} must stay out of navigation until the SDK is published`,
    );
    assert.ok(
      !existsSync(resolve(contractDir, `../../mintlify/${page}.mdx`)),
      `${page}.mdx must stay out of the public docs source until the SDK is published`,
    );
  }
});
