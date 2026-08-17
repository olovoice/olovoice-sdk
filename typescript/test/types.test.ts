import { isKnownCarrierResponse } from '../src/index.js';
import type {
  CarrierResponse,
  CallSttConfig,
  CreateAssistantParams,
  CreateCallParams,
  CreateWebCallParams,
  LlmConfig,
  MetricsResponse,
  RuntimeLlmInput,
  RuntimeTtsInput,
  TtsConfig,
  UpdateAssistantParams,
} from '../src/index.js';

const classicDirectCall = {
  assistantId: 'assistant-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  firstMessage: 'Merhaba',
  content: 'Yardımcı ol.',
  llm: { provider: 'openai', model: 'gpt-4.1-mini' },
  tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
  stt: { provider: 'deepgram', language: 'tr' },
  conversation: {},
  backgroundAudio: {},
} satisfies CreateCallParams;

const classicCallWithRuntimeShorthands = {
  ...classicDirectCall,
  stt: { language: 'tr', keywords: ['OloVoice', { phrase: 'OloGuard', boost: 1.5 }] },
  backgroundAudio: { ambient: 'office', thinking: 'keyboard' },
} satisfies CreateCallParams;

const inferredHalfCascadeCall = {
  squadId: 'squad-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  llm: { provider: 'openai-realtime', model: 'gpt-realtime' },
  tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
  conversation: {},
  backgroundAudio: {},
} satisfies CreateCallParams;

const modelInferredHalfCascadeCall = {
  workflowId: 'workflow-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  llm: { provider: 'openai', model: 'gpt-realtime-2' },
  tts: { provider: 'openai', model: 'gpt-4o-mini-tts', voiceId: 'alloy' },
  conversation: {},
  backgroundAudio: {},
} satisfies CreateCallParams;

const nativeAudioCall = {
  assistantId: 'assistant-1',
  squadId: 'squad-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  llm: {
    provider: 'openai-realtime',
    model: 'gpt-realtime-2',
    realtimeMode: 'nativeAudio',
  },
  conversation: {},
  backgroundAudio: {},
} satisfies CreateCallParams;

const webCall = {
  organizationId: 'org-1',
  assistantId: 'assistant-1',
  llm: { provider: 'openai', model: 'gpt-4.1-mini' },
  tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
  stt: { language: 'tr' },
} satisfies CreateWebCallParams;

const canonicalAssistant = {
  name: 'Destek',
  llm: { provider: 'openai', model: 'gpt-4.1-mini' },
  tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
  stt: {
    provider: 'deepgram',
    keywords: [{ phrase: 'OloVoice', boost: 2 }],
  },
  backgroundAudio: {
    ambient: 'office',
    thinking: { builtin: 'keyboard', volume: 0.3 },
  },
} satisfies CreateAssistantParams;

const validUpdate = { name: 'Yeni isim' } satisfies UpdateAssistantParams;
const validClearUpdate = {
  firstMessage: null,
  content: null,
  serverUrl: null,
} satisfies UpdateAssistantParams;

// @ts-expect-error A plain assistant call cannot hydrate its missing prompt.
const missingDirectPrompt: CreateCallParams = {
  assistantId: 'assistant-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  llm: { provider: 'openai', model: 'gpt-4.1-mini' },
  tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
  stt: { provider: 'deepgram' },
  conversation: {},
  backgroundAudio: {},
};

// @ts-expect-error Outbound calls always require llm/conversation/backgroundAudio and classic tts/stt.
const missingRuntimeConfigs: CreateCallParams = {
  squadId: 'squad-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
};

const invalidNativeAudioProvider: CreateCallParams = {
  squadId: 'squad-1',
  phoneNumberId: 'phone-1',
  customer: { number: '+905551234567' },
  // @ts-expect-error A realtime mode is valid only for a supported realtime provider/model.
  llm: { provider: 'anthropic', model: 'claude-sonnet', realtimeMode: 'nativeAudio' },
  conversation: {},
  backgroundAudio: {},
};

const invalidAssistantKeywords: CreateAssistantParams = {
  name: 'Bad keywords',
  stt: {
    provider: 'deepgram',
    keywords: [
      // @ts-expect-error Assistant CRUD drops shorthand string keywords.
      'OloVoice',
    ],
  },
};

const invalidAssistantThinking: CreateAssistantParams = {
  name: 'Bad thinking audio',
  backgroundAudio: {
    // @ts-expect-error Assistant CRUD drops string thinking audio.
    thinking: 'keyboard',
  },
};

const invalidAssistantStt: CreateAssistantParams = {
  name: 'Missing STT provider',
  // @ts-expect-error Assistant CRUD STT config must identify its provider.
  stt: { language: 'tr' },
};

const invalidAssistantLlm: CreateAssistantParams = {
  name: 'Missing LLM provider/model',
  // @ts-expect-error Provided LLM config must be complete.
  llm: {},
};

const invalidAssistantTts: CreateAssistantParams = {
  name: 'Incomplete TTS config',
  // @ts-expect-error Provided TTS config must match one complete provider-specific shape.
  tts: {},
};

// @ts-expect-error Runtime LLM config must identify its provider.
const missingLlmProvider: RuntimeLlmInput = { model: 'gpt-4.1-mini' };

// @ts-expect-error Runtime LLM config must identify its model.
const missingLlmModel: RuntimeLlmInput = { provider: 'openai' };

const unsupportedLlmProvider: RuntimeLlmInput = {
  // @ts-expect-error The worker does not implement this LLM provider.
  provider: 'ollama',
  model: 'llama3',
};

// @ts-expect-error Runtime TTS config must identify its provider.
const missingTtsProvider: RuntimeTtsInput = { model: 'gpt-4o-mini-tts', voiceId: 'alloy' };

const awsDefaultModel: RuntimeTtsInput = { provider: 'aws', voiceId: 'Filiz' };
const freyaDefaults: RuntimeTtsInput = { provider: 'freya' };
const novaDefaults: RuntimeTtsInput = { provider: 'nova' };

// @ts-expect-error AWS defaults its model but still requires voiceId.
const missingAwsVoice: RuntimeTtsInput = { provider: 'aws' };

// @ts-expect-error OpenAI TTS requires a model.
const missingTtsModel: RuntimeTtsInput = { provider: 'openai', voiceId: 'alloy' };

// @ts-expect-error OpenAI TTS requires voiceId.
const missingTtsVoice: RuntimeTtsInput = { provider: 'openai', model: 'gpt-4o-mini-tts' };

// @ts-expect-error ElevenLabs TTS requires both model and voiceId.
const incompleteElevenTts: RuntimeTtsInput = { provider: 'elevenlabs', voiceId: 'voice-1' };

const unsupportedTtsProvider: RuntimeTtsInput = {
  // @ts-expect-error The worker does not implement this TTS provider.
  provider: 'playht',
  model: 'dialog',
  voiceId: 'voice-1',
};

const unsupportedSttProvider: CallSttConfig = {
  // @ts-expect-error The worker does not implement this STT provider.
  provider: 'assemblyai',
};

// Readback/base configs intentionally remain forward-compatible.
const futureLlmReadback = { provider: 'future-llm', model: null } satisfies LlmConfig;
const futureTtsReadback = { provider: 'future-tts', voiceId: null } satisfies TtsConfig;
const emptyMetricsCurrency: MetricsResponse['summary']['currency'] = null;

// @ts-expect-error Web calls require at least one assistant/squad/workflow selector.
const missingWebSelector: CreateWebCallParams = { organizationId: 'org-1' };

// @ts-expect-error Empty assistant patches deterministically return 400.
const emptyUpdate: UpdateAssistantParams = {};

function describeCarrier(carrier: CarrierResponse): string {
  if (!isKnownCarrierResponse(carrier)) return 'opaque carrier body';
  if (carrier.skipped) return carrier.reason;
  if (carrier.duplicate) return carrier.reason;
  return carrier.callId ?? 'accepted';
}

void [
  classicDirectCall,
  classicCallWithRuntimeShorthands,
  inferredHalfCascadeCall,
  modelInferredHalfCascadeCall,
  nativeAudioCall,
  webCall,
  canonicalAssistant,
  validUpdate,
  validClearUpdate,
  missingDirectPrompt,
  missingRuntimeConfigs,
  invalidNativeAudioProvider,
  invalidAssistantKeywords,
  invalidAssistantThinking,
  invalidAssistantStt,
  invalidAssistantLlm,
  invalidAssistantTts,
  missingLlmProvider,
  missingLlmModel,
  unsupportedLlmProvider,
  missingTtsProvider,
  awsDefaultModel,
  freyaDefaults,
  novaDefaults,
  missingAwsVoice,
  missingTtsModel,
  missingTtsVoice,
  incompleteElevenTts,
  unsupportedTtsProvider,
  unsupportedSttProvider,
  futureLlmReadback,
  futureTtsReadback,
  emptyMetricsCurrency,
  missingWebSelector,
  emptyUpdate,
  describeCarrier,
];
