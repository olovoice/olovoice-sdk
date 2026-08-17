/**
 * Types for the olovoice Public API (https://api.olovoice.ai).
 *
 * All field names are camelCase — the API rejects snake_case with 400.
 * Config objects (llm, tts, stt, …) accept provider-specific extra keys, so
 * they are typed with an index signature; see the Field reference guide at
 * https://docs.olovoice.ai for the full sub-field list.
 */

// ---------------------------------------------------------------------------
// Shared config objects
// ---------------------------------------------------------------------------

export type RealtimeMode = 'halfCascade' | 'nativeAudio';

export interface LlmConfig {
  provider?: string | null;
  model?: string | null;
  /** Present only for supported realtime provider/model combinations. */
  realtimeMode?: RealtimeMode | null;
  [key: string]: unknown;
}

/** Provider names currently implemented by the call worker. */
export type RuntimeLlmProvider =
  | 'openai'
  | 'openai_realtime'
  | 'openai-realtime'
  | 'openai.realtime'
  | 'google'
  | 'gemini'
  | 'anthropic'
  | 'aws'
  | 'amazon'
  | 'bedrock'
  | 'groq'
  | 'groq.ai'
  | 'groqai'
  | 'qwen';

/** Complete LLM input forwarded to the worker. */
export interface RuntimeLlmInput extends LlmConfig {
  provider: RuntimeLlmProvider;
  model: string;
}

export type OpenAiRealtimeProvider =
  | 'openai-realtime'
  | 'openai_realtime'
  | 'openai.realtime';

export type OpenAiRealtimeModel =
  | 'gpt-realtime'
  | 'gpt-realtime-1.5'
  | 'gpt-realtime-2';

export type OpenAiRealtimeLlmInput =
  | (RuntimeLlmInput & { provider: OpenAiRealtimeProvider })
  | (RuntimeLlmInput & { provider: 'openai'; model: OpenAiRealtimeModel });

export interface TtsConfig {
  provider?: string | null;
  model?: string | null;
  voiceId?: string | null;
  optimizeStreamingLatency?: number | null;
  autoMode?: boolean | null;
  speed?: number | null;
  volume?: number | null;
  instructions?: string | null;
  [key: string]: unknown;
}

export type RuntimeAwsTtsProvider = 'aws' | 'amazon' | 'polly';
export type RuntimeDefaultingTtsProvider =
  | 'freya'
  | 'freyavoice'
  | 'nova'
  | 'novaforge'
  | 'nova-tts';
export type RuntimeStrictTtsProvider = 'elevenlabs' | 'eleven' | 'openai';

/** Provider names currently implemented by the call worker. */
export type RuntimeTtsProvider =
  | RuntimeAwsTtsProvider
  | RuntimeDefaultingTtsProvider
  | RuntimeStrictTtsProvider;

/** Complete provider-specific TTS input forwarded to the worker. */
export type RuntimeTtsInput =
  | (TtsConfig & {
      provider: RuntimeAwsTtsProvider;
      /** AWS Polly defaults to `polly-neural`, but always needs a voice. */
      voiceId: string;
    })
  | (TtsConfig & {
      /** Freya and Nova provide model and voice defaults. */
      provider: RuntimeDefaultingTtsProvider;
    })
  | (TtsConfig & {
      /** ElevenLabs and OpenAI require both fields at runtime. */
      provider: RuntimeStrictTtsProvider;
      model: string;
      voiceId: string;
    });

/** Provider names currently implemented by the call worker. */
export type RuntimeSttProvider =
  | 'azure'
  | 'azure_speech'
  | 'azure-speech'
  | 'aws'
  | 'amazon'
  | 'transcribe'
  | 'transcribe-streaming'
  | 'deepgram'
  | 'dg'
  | 'elevenlabs'
  | 'eleven'
  | 'eleven-labs'
  | 'freya'
  | 'freyavoice'
  | 'groq'
  | 'groq.ai'
  | 'groqai'
  | 'nova'
  | 'novaforge'
  | 'nova-stt'
  | 'openai'
  | 'whisper';

interface SttConfigBase {
  provider?: string | null;
  model?: string | null;
  language?: string | null;
  interimResults?: boolean | null;
  smartFormat?: boolean | null;
  optimizationProfile?: 'balanced' | 'noisy-call' | 'domain-terms' | string | null;
  keyterms?: string[];
  endpointingMs?: number | null;
  fillerWords?: boolean | null;
  noDelay?: boolean | null;
  profanityFilter?: boolean | null;
  mipOptOut?: boolean | null;
  punctuate?: boolean | null;
  numerals?: boolean | null;
  tags?: string[];
  eagerEotThreshold?: number | null;
  eotThreshold?: number | null;
  eotTimeoutMs?: number | null;
  autoConvertKeytermsToKeywords?: boolean | null;
  keytermBoost?: number | null;
  enableTurkishPhoneShortPhraseBoosts?: boolean | null;
  [key: string]: unknown;
}

export interface SttKeyword {
  phrase: string;
  boost?: number | null;
}

/** Runtime call config; the worker accepts shorthand string keyword entries. */
export interface CallSttConfig extends SttConfigBase {
  provider?: RuntimeSttProvider | null;
  keywords?: Array<string | SttKeyword>;
  keywordBoosts?: Array<string | SttKeyword>;
}

/** Assistant CRUD config; string keyword entries would be silently discarded. */
export interface AssistantSttConfig extends SttConfigBase {
  provider: RuntimeSttProvider;
  keywords?: SttKeyword[];
  keywordBoosts?: SttKeyword[];
}

/** Backwards-compatible name for the call-runtime STT shape. */
export type SttConfig = CallSttConfig;

/** Canonical assistant readback shape, including legacy nullable providers. */
export interface AssistantSttResponseConfig extends SttConfigBase {
  keywords?: SttKeyword[];
  keywordBoosts?: SttKeyword[];
}

export interface ConversationConfig {
  allowInterruptions?: boolean;
  firstMessageMode?: string;
  mem0Enabled?: boolean;
  rulesEnabled?: boolean;
  handoffEnabled?: boolean;
  handoffNumber?: string | null;
  [key: string]: unknown;
}

export interface BackgroundAudioClipConfig {
  builtin: string | null;
  volume?: number | null;
}

/** Runtime call config; the worker accepts builtin strings for both channels. */
export interface CallBackgroundAudioConfig {
  ambient?: string | BackgroundAudioClipConfig | null;
  thinking?: string | BackgroundAudioClipConfig | null;
  [key: string]: unknown;
}

/** Assistant CRUD config; a string `thinking` value would be silently discarded. */
export interface AssistantBackgroundAudioConfig {
  ambient?: string | BackgroundAudioClipConfig | null;
  thinking?: BackgroundAudioClipConfig | null;
  [key: string]: unknown;
}

/** Backwards-compatible name for the call-runtime background-audio shape. */
export type BackgroundAudioConfig = CallBackgroundAudioConfig;

export interface PrivacyConfig {
  hipaaCompliant?: boolean;
  recordCalls?: boolean;
  ologuardEnabled?: boolean;
  message?: string | null;
  serverUrl?: string | null;
  [key: string]: unknown;
}

export interface PredefinedFunctionsConfig {
  enableEndCallFunction?: boolean;
  enableDialKeypad?: boolean;
  enableDtmfCapture?: boolean;
  endCallMessages?: string[];
  [key: string]: unknown;
}

/** Inline tool definition. Requires `name` + HTTPS `webhookUrl` + `method`. */
export interface InlineTool {
  name: string;
  webhookUrl: string;
  method: string;
  [key: string]: unknown;
}

export interface SubscriptionLimits {
  concurrencyBlocked: boolean;
  concurrencyLimit: number;
  remainingConcurrentCalls: number;
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

interface CreateCallBase {
  /** Org phone number to dial from. Must support outbound and have a trunk. */
  phoneNumberId: string;
  customer: {
    /** Destination number, `^\+?[0-9]{6,20}$`. E.164 recommended. */
    number: string;
    name?: string;
  };
  /** HTTPS post-call report webhook. */
  serverUrl?: string;
  /** Always required for outbound calls. */
  conversation: ConversationConfig;
  /** Always required for outbound calls. */
  backgroundAudio: CallBackgroundAudioConfig;
  privacy?: PrivacyConfig;
  predefinedFunctions?: PredefinedFunctionsConfig;
  tools?: InlineTool[];
  toolIds?: string[];
  structuredOutputIds?: string[];
  /** Knowledge-base file IDs. */
  fileIds?: string[];
  extras?: Record<string, unknown>;
}

type DirectAssistantPrompt = {
  assistantId: string;
  squadId?: never;
  workflowId?: never;
  /** Opening line. A plain assistant call cannot hydrate this field. */
  firstMessage: string;
  /** System prompt. A plain assistant call cannot hydrate this field. */
  content: string;
};

type SquadPrompt = {
  squadId: string;
  assistantId?: string;
  workflowId?: string;
  /** Optional when the squad/workflow supplies it. */
  firstMessage?: string;
  /** Optional when the squad/workflow supplies it. */
  content?: string;
};

type WorkflowPrompt = {
  workflowId: string;
  assistantId?: string;
  squadId?: string;
  /** Optional when the workflow/squad supplies it. */
  firstMessage?: string;
  /** Optional when the workflow/squad supplies it. */
  content?: string;
};

type ClassicAudioPipeline = {
  llm: RuntimeLlmInput & { realtimeMode?: null };
  tts: RuntimeTtsInput;
  stt: CallSttConfig;
};

type HalfCascadeAudioPipeline = {
  llm: OpenAiRealtimeLlmInput & { realtimeMode?: 'halfCascade' | null };
  tts: RuntimeTtsInput;
  stt?: CallSttConfig;
};

type NativeAudioPipeline = {
  llm: OpenAiRealtimeLlmInput & { realtimeMode: 'nativeAudio' };
  tts?: RuntimeTtsInput;
  stt?: CallSttConfig;
};

/**
 * Outbound call payload. Multiple selectors are accepted. A plain
 * `assistantId` call must carry its prompt; squad/workflow calls may hydrate it.
 */
export type CreateCallParams = CreateCallBase &
  (DirectAssistantPrompt | SquadPrompt | WorkflowPrompt) &
  (ClassicAudioPipeline | HalfCascadeAudioPipeline | NativeAudioPipeline);

export interface CarrierAcceptedResponse {
  ok: true;
  duplicate?: false;
  skipped?: false;
  /** The current dialer normally omits this; older carriers may return it. */
  callId?: string | null;
  [key: string]: unknown;
}

export interface CarrierDuplicateResponse {
  ok: true;
  duplicate: true;
  skipped?: false;
  reason: string;
  requestId?: string | null;
  callId?: string | null;
  activeStatus?: string | null;
  [key: string]: unknown;
}

export interface CarrierSkippedResponse {
  ok: true;
  skipped: true;
  duplicate?: false;
  status: string;
  reason: string;
  endedReason?: string;
  /** Forwarded verbatim from the dialer response. */
  ended_at?: string;
  activeCallId?: string | null;
  activeStatus?: string | null;
  [key: string]: unknown;
}

export type KnownCarrierResponse =
  | CarrierAcceptedResponse
  | CarrierDuplicateResponse
  | CarrierSkippedResponse;

/** Carrier bodies are forwarded verbatim and can contain any JSON value or raw text. */
export type CarrierJsonValue =
  | string
  | number
  | boolean
  | null
  | CarrierJsonValue[]
  | { [key: string]: CarrierJsonValue };

export type CarrierResponse = KnownCarrierResponse | CarrierJsonValue;

/** Narrow an opaque carrier body to the SDK's known accepted/duplicate/skipped shapes. */
export function isKnownCarrierResponse(value: unknown): value is KnownCarrierResponse {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const carrier = value as Record<string, unknown>;
  if (carrier.ok !== true) return false;

  if (carrier.duplicate === true) {
    return (
      (carrier.skipped === undefined || carrier.skipped === false) &&
      typeof carrier.reason === 'string' &&
      optionalNullableString(carrier.requestId) &&
      optionalNullableString(carrier.callId) &&
      optionalNullableString(carrier.activeStatus)
    );
  }

  if (carrier.skipped === true) {
    return (
      (carrier.duplicate === undefined || carrier.duplicate === false) &&
      typeof carrier.status === 'string' &&
      typeof carrier.reason === 'string' &&
      optionalString(carrier.endedReason) &&
      optionalString(carrier.ended_at) &&
      optionalNullableString(carrier.activeCallId) &&
      optionalNullableString(carrier.activeStatus)
    );
  }

  return (
    (carrier.duplicate === undefined || carrier.duplicate === false) &&
    (carrier.skipped === undefined || carrier.skipped === false) &&
    optionalNullableString(carrier.callId)
  );
}

function optionalString(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function optionalNullableString(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string';
}

export interface CreateCallResponse {
  success: boolean;
  subscriptionLimits: SubscriptionLimits;
  payload: {
    callId: string;
    assistantId?: string;
    phoneNumberId: string;
    customer: { number: string; name?: string };
    organizationId: string;
    requestId: string;
    [key: string]: unknown;
  };
  carrier: CarrierResponse;
}

interface CreateWebCallBase {
  organizationId: string;
  customer?: {
    /** Display name only — a web call is not dialed. */
    name?: string;
  };
  firstMessage?: string;
  content?: string;
  serverUrl?: string;
  llm?: RuntimeLlmInput;
  tts?: RuntimeTtsInput;
  stt?: CallSttConfig;
  conversation?: ConversationConfig;
  backgroundAudio?: CallBackgroundAudioConfig;
  privacy?: PrivacyConfig;
  predefinedFunctions?: PredefinedFunctionsConfig;
  /** Inline tools only — a top-level `toolIds` is ignored for web calls. */
  tools?: InlineTool[];
  structuredOutputIds?: string[];
  fileIds?: string[];
  extras?: Record<string, unknown>;
}

type AnyCallSelector =
  | { assistantId: string; squadId?: string; workflowId?: string }
  | { squadId: string; assistantId?: string; workflowId?: string }
  | { workflowId: string; assistantId?: string; squadId?: string };

/** `organizationId` must equal your API key's organization; one selector is required. */
export type CreateWebCallParams = CreateWebCallBase & AnyCallSelector;

export interface CreateWebCallResponse {
  success: boolean;
  callId: string;
  roomName: string;
  /** Short-lived LiveKit participant JWT — pass to the LiveKit client SDK. */
  token: string;
  livekitUrl: string;
  expiresInSeconds: number;
  startedAt: string;
  subscriptionLimits: SubscriptionLimits;
}

// ---------------------------------------------------------------------------
// Call logs
// ---------------------------------------------------------------------------

export interface CallLog {
  id: string;
  callId: string;
  assistantId: string | null;
  assistantName: string | null;
  idempotencyKey: string | null;
  callType: string;
  status: string;
  startedAt: string;
  endedAt: string | null;
  endReason: string | null;
  durationSeconds: number | null;
  customerName: string | null;
  customerPhone: string | null;
  organizationPhoneNumber: string | null;
  phoneNumberProvider: string | null;
  recordingUrl: string | null;
  recordingAssistantUrl: string | null;
  recordingCustomerUrl: string | null;
  firstMessage: string | null;
  mainPrompt: string | null;
  serverUrl: string | null;
  analysisSummary: string | null;
  analysisSuccess: boolean | null;
  analysisScore: number | null;
  analysisSentiment: string | null;
  analysisStatus: string | null;
  costCurrency: string | null;
  costTotal: number | null;
  analysis: {
    summary: string | null;
    success: boolean | null;
    score: number | null;
    sentiment: string | null;
    reasons: unknown;
  } | null;
  aiDisclosures: Record<
    string,
    { label: string; source: string; provider: string | null; model: string | null }
  > | null;
  timeline: unknown[] | null;
  toolRuns: unknown[] | null;
  structuredOutputs: unknown[] | null;
  metadata: Record<string, unknown> | null;
  /** Public list/detail endpoints never expose the raw internal payload. */
  payload: null;
  publicPayload: Record<string, unknown> | null;
  history: unknown[];
  createdAt: string;
  updatedAt: string;
  [key: string]: unknown;
}

export interface ListCallLogsParams {
  /** Records per page. Default 25, min 1, max 100. */
  limit?: number;
  /** 1-based page. Default 1. */
  page?: number;
  /** Optional; if sent, must equal the API key's organization. */
  organizationId?: string;
}

export interface ListCallLogsResponse {
  data: CallLog[];
  meta: { page: number; limit: number; total: number; totalPages: number };
  permissions: { canManageCallLogs: boolean };
}

export interface GetCallLogResponse {
  data: CallLog;
  permissions: { canManageCallLogs: boolean };
}

export interface RecordingUrlResponse {
  data: {
    callId: string;
    recordingUrl: string | null;
    recordingAssistantUrl: string | null;
    recordingCustomerUrl: string | null;
    expiresInSeconds: number;
  };
}

// ---------------------------------------------------------------------------
// Assistants
// ---------------------------------------------------------------------------

export interface Assistant {
  id: string;
  orgId: string;
  name: string;
  slug: string;
  status: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  firstMessage: string | null;
  content: string | null;
  serverUrl: string | null;
  llm: LlmConfig;
  tts: TtsConfig;
  stt: AssistantSttResponseConfig;
  conversation: ConversationConfig;
  backgroundAudio: AssistantBackgroundAudioConfig;
  privacy: PrivacyConfig;
  predefinedFunctions: PredefinedFunctionsConfig;
  toolIds: string[];
  structuredOutputIds: string[];
  knowledgeFileIds: string[];
  folderId: string | null;
  usePronunciationLibrary: boolean;
  pronunciationLibraryId: string | null;
  [key: string]: unknown;
}

export interface CreateAssistantParams {
  name: string;
  /** `draft` or `published`; anything else coerces to `draft`. */
  status?: 'draft' | 'published';
  firstMessage?: string;
  /** System prompt (aka mainPrompt). */
  content?: string;
  /** Defaults to `status === "published"`. */
  isActive?: boolean;
  serverUrl?: string;
  folderId?: string | null;
  llm?: RuntimeLlmInput;
  tts?: RuntimeTtsInput;
  stt?: AssistantSttConfig;
  conversation?: ConversationConfig;
  backgroundAudio?: AssistantBackgroundAudioConfig;
  privacy?: PrivacyConfig;
  predefinedFunctions?: PredefinedFunctionsConfig;
  toolIds?: string[];
  structuredOutputIds?: string[];
  knowledgeFileIds?: string[];
  usePronunciationLibrary?: boolean;
  /** Required if `usePronunciationLibrary`; needs `tts.provider = elevenlabs`. */
  pronunciationLibraryId?: string | null;
}

/**
 * Partial update — only top-level keys present are changed. Nested config
 * objects are FULLY REPLACED (not deep-merged), except `privacy.ologuardEnabled`
 * which is preserved if omitted. An empty body returns 400.
 */
type AtLeastOne<T> = Partial<T> & {
  [K in keyof T]-?: Required<Pick<T, K>>;
}[keyof T];

type AssistantUpdateFields = Omit<Partial<CreateAssistantParams>, 'firstMessage' | 'content' | 'serverUrl'> & {
  /** Send `null` to clear the stored opening line. */
  firstMessage?: string | null;
  /** Send `null` to clear the stored system prompt. */
  content?: string | null;
  /** Send `null` to clear the post-call webhook URL. */
  serverUrl?: string | null;
};

export type UpdateAssistantParams = AtLeastOne<AssistantUpdateFields>;

export interface ListAssistantsParams {
  /** Max assistants. Clamped to [1, 20]; default 20. */
  limit?: number;
}

export interface ListAssistantsResponse {
  success: boolean;
  assistants: Assistant[];
}

export interface AssistantResponse {
  success: true;
  assistant: Assistant;
}

/** Normal create response or the server's degraded readback fallback. */
export type CreateAssistantResponse =
  | AssistantResponse
  | {
      success: true;
      assistantId: string;
      warning: string;
    };

/** Normal update response or the server's degraded readback fallback. */
export type UpdateAssistantResponse =
  | AssistantResponse
  | {
      success: true;
      warning: string;
    };

export interface DeleteAssistantResponse {
  success: boolean;
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export interface CreateLeadParams {
  name: string;
  phone: string;
  email?: string;
  /** Exposed to the prompt as `{{lead_<key>}}`; keys must match `^[a-zA-Z0-9_]+$`. */
  metadata?: Record<string, unknown>;
  /** If the category has an assistant + phone number, a call is placed automatically. */
  categoryId?: string;
  campaignId?: string;
}

export interface CreateLeadResponse {
  success: boolean;
  lead_id: string;
  call?: { status: string; [key: string]: unknown };
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export type MetricsRange = '7d' | '30d' | '90d' | '180d' | '365d' | 'custom';

export interface GetMetricsParams {
  range?: MetricsRange;
  /** YYYY-MM-DD. Required only when `range` is `custom`. */
  startDate?: string;
  /** YYYY-MM-DD (end-of-day UTC). Required only when `range` is `custom`. */
  endDate?: string;
  /** Filter to one assistant; `all` == no filter. */
  assistantId?: string;
  organizationId?: string;
}

export interface LatencyBreakdown {
  avgTurnEndDelayMs: number;
  avgLlmTtftMs: number;
  avgRealtimeTtftMs: number;
  avgTtsTtfbMs: number;
  avgPlaybackLatencyMs: number;
  avgTotalLatencyMs: number;
  sampleCount: number;
  dominantSource: string;
  dominantLabel: string;
}

export interface MetricsResponse {
  summary: {
    totalCalls: number;
    totalDuration: number;
    totalCost: number;
    successRate: number;
    analysisCoverage: number;
    answeredRate: number;
    answeredCalls: number;
    analyzedCalls: number;
    pendingAnalysisCalls: number;
    ruleCompliance: number;
    totalInputTokens: number;
    totalOutputTokens: number;
    avgLatencyMs: number;
    latencyBreakdown: LatencyBreakdown;
    currency: string | null;
    rules: { passed: number; partial: number; failed: number; checked: number };
    [key: string]: unknown;
  };
  trends: Array<{ date: string; calls: number; cost: number; [key: string]: unknown }>;
  hourlyActivity: Array<{ hour: number; calls: number }>;
  durationDistribution: Array<{ range: string; count: number }>;
  disconnectReasons: Array<{ reason: string; count: number }>;
  sentimentAnalysis: Array<{ name: string; value: number; color: string }>;
  funnel: { initiated: number; answered: number; success: number };
  topAssistants: Array<{ id: string; name: string; calls: number; [key: string]: unknown }>;
  toolUsage: Array<{ name: string; count: number; success: number; fail: number }>;
  [key: string]: unknown;
}
