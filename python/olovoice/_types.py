"""Public request and response types for the olovoice SDK."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict, Union


JSONScalar = Union[None, bool, int, float, str]
JSONValue = Union[JSONScalar, List["JSONValue"], Dict[str, "JSONValue"]]
JSONObject = Dict[str, JSONValue]
AssistantStatus = Literal["draft", "published"]
MetricsRange = Literal["7d", "30d", "90d", "180d", "365d", "custom"]
RuntimeLlmProvider = Literal[
    "openai",
    "openai_realtime",
    "openai-realtime",
    "openai.realtime",
    "google",
    "gemini",
    "anthropic",
    "aws",
    "amazon",
    "bedrock",
    "groq",
    "groq.ai",
    "groqai",
    "qwen",
]
RuntimeTtsProvider = Literal[
    "aws",
    "amazon",
    "elevenlabs",
    "eleven",
    "freya",
    "freyavoice",
    "nova",
    "novaforge",
    "nova-tts",
    "openai",
    "polly",
]
RuntimeSttProvider = Literal[
    "azure",
    "azure_speech",
    "azure-speech",
    "aws",
    "amazon",
    "transcribe",
    "transcribe-streaming",
    "deepgram",
    "dg",
    "elevenlabs",
    "eleven",
    "eleven-labs",
    "freya",
    "freyavoice",
    "groq",
    "groq.ai",
    "groqai",
    "nova",
    "novaforge",
    "nova-stt",
    "openai",
    "whisper",
]


class _CustomerRequired(TypedDict):
    number: str


class Customer(_CustomerRequired, total=False):
    name: str


class WebCustomer(TypedDict, total=False):
    number: str
    name: str


class LlmConfig(TypedDict, total=False):
    provider: Optional[str]
    model: Optional[str]
    temperature: float
    maxTokens: int
    realtimeMode: Optional[Literal["halfCascade", "nativeAudio"]]


class _RuntimeLlmInputRequired(TypedDict):
    provider: RuntimeLlmProvider
    model: str


class RuntimeLlmInput(_RuntimeLlmInputRequired, total=False):
    temperature: float
    maxTokens: int
    realtimeMode: Optional[Literal["halfCascade", "nativeAudio"]]


class TtsConfig(TypedDict, total=False):
    provider: Optional[str]
    model: Optional[str]
    voiceId: Optional[str]
    language: str
    optimizeStreamingLatency: Optional[int]
    autoMode: Optional[bool]
    speed: Optional[float]
    volume: Optional[float]
    instructions: Optional[str]


class _RuntimeTtsOptions(TypedDict, total=False):
    language: str
    optimizeStreamingLatency: Optional[int]
    autoMode: Optional[bool]
    speed: Optional[float]
    volume: Optional[float]
    instructions: Optional[str]


class _AwsRuntimeTtsInputRequired(TypedDict):
    provider: Literal["aws", "amazon", "polly"]
    voiceId: str


class AwsRuntimeTtsInput(_AwsRuntimeTtsInputRequired, _RuntimeTtsOptions, total=False):
    model: str


class _DefaultedRuntimeTtsInputRequired(TypedDict):
    provider: Literal["freya", "freyavoice", "nova", "novaforge", "nova-tts"]


class DefaultedRuntimeTtsInput(
    _DefaultedRuntimeTtsInputRequired, _RuntimeTtsOptions, total=False
):
    model: str
    voiceId: str


class _FullRuntimeTtsInputRequired(TypedDict):
    provider: Literal["elevenlabs", "eleven", "openai"]
    model: str
    voiceId: str


class FullRuntimeTtsInput(
    _FullRuntimeTtsInputRequired, _RuntimeTtsOptions, total=False
):
    pass


RuntimeTtsInput = Union[
    AwsRuntimeTtsInput,
    DefaultedRuntimeTtsInput,
    FullRuntimeTtsInput,
]


class _KeywordBoostRequired(TypedDict):
    phrase: str


class KeywordBoost(_KeywordBoostRequired, total=False):
    boost: Optional[float]


class CallSttConfig(TypedDict, total=False):
    provider: Optional[RuntimeSttProvider]
    model: Optional[str]
    language: Optional[str]
    interimResults: Optional[bool]
    smartFormat: Optional[bool]
    optimizationProfile: str
    keywords: List[Union[str, KeywordBoost]]
    keywordBoosts: List[Union[str, KeywordBoost]]
    keyterms: List[str]


class _AssistantSttConfigRequired(TypedDict):
    provider: RuntimeSttProvider


class AssistantSttConfig(_AssistantSttConfigRequired, total=False):
    model: Optional[str]
    language: Optional[str]
    interimResults: Optional[bool]
    smartFormat: Optional[bool]
    optimizationProfile: str
    keywords: List[KeywordBoost]
    keywordBoosts: List[KeywordBoost]
    keyterms: List[str]


class AssistantSttResponseConfig(TypedDict, total=False):
    provider: Optional[str]
    model: Optional[str]
    language: Optional[str]
    interimResults: Optional[bool]
    smartFormat: Optional[bool]
    optimizationProfile: str
    keywords: List[KeywordBoost]
    keywordBoosts: List[KeywordBoost]
    keyterms: List[str]


class ConversationConfig(TypedDict, total=False):
    allowInterruptions: bool
    firstMessageMode: str
    mem0Enabled: bool
    rulesEnabled: bool
    handoffEnabled: bool
    handoffNumber: Optional[str]
    timezone: str
    minEndpointingDelay: float
    maxEndpointingDelay: float
    minConsecutiveSpeechDelay: float


class CallBackgroundAudio(TypedDict, total=False):
    ambient: Union[str, JSONObject]
    thinking: Union[str, JSONObject]


class BackgroundAudioClip(TypedDict, total=False):
    builtin: Optional[str]
    volume: Optional[float]


class AssistantBackgroundAudio(TypedDict, total=False):
    ambient: Union[str, BackgroundAudioClip, None]
    thinking: Optional[BackgroundAudioClip]


class PrivacyConfig(TypedDict, total=False):
    hipaaCompliant: bool
    recordCalls: bool
    ologuardEnabled: bool
    message: Optional[str]
    serverUrl: Optional[str]


class PredefinedFunctionsConfig(TypedDict, total=False):
    enableEndCallFunction: bool
    enableDialKeypad: bool
    enableDtmfCapture: bool
    endCallMessages: List[str]


class _InlineToolRequired(TypedDict):
    name: str
    webhookUrl: str
    method: str


class InlineTool(_InlineToolRequired, total=False):
    description: Optional[str]
    inputSchema: JSONObject
    responsePath: Optional[str]
    speakResult: bool
    speakTemplate: Optional[str]
    headers: Dict[str, str]
    includeMetadata: bool
    metadataKey: Optional[str]
    staticPayload: JSONObject
    timeoutSec: float


class _CreateCallParamsRequired(TypedDict):
    phone_number_id: str
    customer: Customer
    llm: RuntimeLlmInput
    conversation: ConversationConfig
    background_audio: CallBackgroundAudio


class CreateCallParams(_CreateCallParamsRequired, total=False):
    assistant_id: str
    squad_id: str
    workflow_id: str
    first_message: str
    content: str
    server_url: str
    tts: RuntimeTtsInput
    stt: CallSttConfig
    privacy: PrivacyConfig
    predefined_functions: PredefinedFunctionsConfig
    tools: List[InlineTool]
    tool_ids: List[str]
    structured_output_ids: List[str]
    file_ids: List[str]
    extras: JSONObject
    pronunciation_library_id: str


class _CreateWebCallParamsRequired(TypedDict):
    organization_id: str


class CreateWebCallParams(_CreateWebCallParamsRequired, total=False):
    assistant_id: str
    squad_id: str
    workflow_id: str
    customer: WebCustomer
    first_message: str
    content: str
    server_url: str
    llm: RuntimeLlmInput
    tts: RuntimeTtsInput
    stt: CallSttConfig
    conversation: ConversationConfig
    background_audio: CallBackgroundAudio
    privacy: PrivacyConfig
    predefined_functions: PredefinedFunctionsConfig
    tools: List[InlineTool]
    structured_output_ids: List[str]
    file_ids: List[str]
    extras: JSONObject


class _CreateAssistantParamsRequired(TypedDict):
    name: str


class CreateAssistantParams(_CreateAssistantParamsRequired, total=False):
    status: AssistantStatus
    first_message: str
    content: str
    is_active: bool
    server_url: str
    folder_id: Optional[str]
    llm: RuntimeLlmInput
    tts: RuntimeTtsInput
    stt: AssistantSttConfig
    conversation: ConversationConfig
    background_audio: AssistantBackgroundAudio
    privacy: PrivacyConfig
    predefined_functions: PredefinedFunctionsConfig
    tool_ids: List[str]
    structured_output_ids: List[str]
    knowledge_file_ids: List[str]
    use_pronunciation_library: bool
    pronunciation_library_id: Optional[str]


class UpdateAssistantParams(TypedDict, total=False):
    name: str
    status: AssistantStatus
    first_message: Optional[str]
    content: Optional[str]
    is_active: bool
    server_url: Optional[str]
    folder_id: Optional[str]
    llm: Optional[RuntimeLlmInput]
    tts: Optional[RuntimeTtsInput]
    stt: Optional[AssistantSttConfig]
    conversation: Optional[ConversationConfig]
    background_audio: Optional[AssistantBackgroundAudio]
    privacy: Optional[PrivacyConfig]
    predefined_functions: Optional[PredefinedFunctionsConfig]
    tool_ids: List[str]
    structured_output_ids: List[str]
    knowledge_file_ids: List[str]
    use_pronunciation_library: bool
    pronunciation_library_id: Optional[str]


class _CreateLeadParamsRequired(TypedDict):
    name: str
    phone: str


class CreateLeadParams(_CreateLeadParamsRequired, total=False):
    email: str
    metadata: JSONObject
    category_id: str
    campaign_id: str


class SubscriptionLimits(TypedDict):
    concurrencyBlocked: bool
    concurrencyLimit: int
    remainingConcurrentCalls: int


class _CallPayloadRequired(TypedDict):
    callId: str
    phoneNumberId: str
    customer: Customer
    organizationId: str
    requestId: str


class CallPayload(_CallPayloadRequired, total=False):
    assistantId: str


class CarrierResult(TypedDict, total=False):
    ok: bool
    callId: str
    skipped: bool
    duplicate: bool
    reason: str


class CreateCallResponse(TypedDict):
    success: bool
    subscriptionLimits: SubscriptionLimits
    payload: CallPayload
    carrier: JSONValue


class CreateWebCallResponse(TypedDict):
    success: bool
    callId: str
    roomName: str
    token: str
    connectionUrl: str
    expiresInSeconds: int
    startedAt: str
    subscriptionLimits: SubscriptionLimits


class CallAnalysis(TypedDict, total=False):
    summary: Optional[str]
    success: Optional[bool]
    score: Optional[float]
    sentiment: Optional[str]
    reasons: JSONValue


AiDisclosureLabel = Literal[
    "AI-generated", "AI-assisted", "AI-transcribed", "AI-extracted"
]


class AiDisclosure(TypedDict):
    label: AiDisclosureLabel
    source: str
    provider: Optional[str]
    model: Optional[str]


class CallLogHistoryEntry(TypedDict):
    timestamp: str
    level: Literal["Info", "Warning", "Error"]
    category: str
    message: str
    raw: JSONValue


class StructuredOutputResult(TypedDict):
    id: str
    structuredOutputId: str
    name: Optional[str]
    description: Optional[str]
    status: Optional[str]
    result: JSONValue
    errorMessage: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    latencyMs: Optional[float]
    tokensUsed: Optional[float]
    createdAt: Optional[str]
    updatedAt: Optional[str]


class CallLog(TypedDict):
    id: str
    callId: str
    assistantId: Optional[str]
    assistantName: Optional[str]
    idempotencyKey: Optional[str]
    callType: str
    status: str
    startedAt: str
    endedAt: Optional[str]
    endReason: Optional[str]
    durationSeconds: Optional[float]
    customerName: Optional[str]
    customerPhone: Optional[str]
    organizationPhoneNumber: Optional[str]
    phoneNumberProvider: Optional[str]
    recordingUrl: Optional[str]
    recordingAssistantUrl: Optional[str]
    recordingCustomerUrl: Optional[str]
    artifactSuppressedReason: Optional[str]
    firstMessage: Optional[str]
    mainPrompt: Optional[str]
    serverUrl: Optional[str]
    analysisSummary: Optional[str]
    analysisSuccess: Optional[bool]
    analysisScore: Optional[float]
    analysisSentiment: Optional[str]
    analysisReasons: Optional[str]
    analysisStatus: Optional[str]
    analysisError: Optional[str]
    analysisStartedAt: Optional[str]
    analysisCompletedAt: Optional[str]
    ruleSuccessCount: int
    ruleFailureCount: int
    rulePartialCount: int
    costCurrency: Optional[str]
    costTotal: Optional[float]
    toolRuns: Optional[List[JSONValue]]
    analysis: Optional[CallAnalysis]
    aiDisclosures: Optional[Dict[str, AiDisclosure]]
    artifact: Optional[JSONObject]
    timeline: Optional[List[JSONValue]]
    ruleChecklist: Optional[JSONObject]
    structuredOutputs: Optional[List[StructuredOutputResult]]
    metadata: Optional[JSONObject]
    payload: None
    publicPayload: Optional[JSONObject]
    history: List[CallLogHistoryEntry]
    createdAt: str
    updatedAt: str


class PaginationMeta(TypedDict):
    page: int
    limit: int
    total: int
    totalPages: int


class Permissions(TypedDict):
    canManageCallLogs: bool


class ListCallLogsResponse(TypedDict):
    data: List[CallLog]
    meta: PaginationMeta
    permissions: Permissions


class GetCallLogResponse(TypedDict):
    data: CallLog
    permissions: Permissions


class RecordingUrlData(TypedDict):
    callId: str
    recordingUrl: Optional[str]
    recordingAssistantUrl: Optional[str]
    recordingCustomerUrl: Optional[str]
    expiresInSeconds: int


class RecordingUrlResponse(TypedDict):
    data: RecordingUrlData


class Assistant(TypedDict):
    id: str
    orgId: str
    name: str
    slug: str
    status: str
    isActive: bool
    firstMessage: Optional[str]
    content: Optional[str]
    serverUrl: Optional[str]
    llm: LlmConfig
    tts: TtsConfig
    stt: AssistantSttResponseConfig
    conversation: JSONObject
    backgroundAudio: JSONObject
    privacy: JSONObject
    predefinedFunctions: JSONObject
    toolIds: List[str]
    structuredOutputIds: List[str]
    knowledgeFileIds: List[str]
    folderId: Optional[str]
    usePronunciationLibrary: bool
    pronunciationLibraryId: Optional[str]
    createdAt: str
    updatedAt: str


class _SuccessResponse(TypedDict):
    success: bool


class ListAssistantsResponse(_SuccessResponse):
    assistants: List[Assistant]


class AssistantObjectResponse(_SuccessResponse):
    assistant: Assistant


class CreateAssistantFallbackResponse(_SuccessResponse):
    assistantId: str
    warning: str


class UpdateAssistantFallbackResponse(_SuccessResponse):
    warning: str


AssistantResponse = Union[
    AssistantObjectResponse,
    CreateAssistantFallbackResponse,
    UpdateAssistantFallbackResponse,
]
CreateAssistantResponse = Union[
    AssistantObjectResponse,
    CreateAssistantFallbackResponse,
]
UpdateAssistantResponse = Union[
    AssistantObjectResponse,
    UpdateAssistantFallbackResponse,
]


class DeleteAssistantResponse(_SuccessResponse):
    pass


class _CreateLeadResponseRequired(TypedDict):
    success: bool
    lead_id: str


class CreateLeadResponse(_CreateLeadResponseRequired, total=False):
    call: JSONObject


class LatencyBreakdown(TypedDict):
    avgTurnEndDelayMs: float
    avgLlmTtftMs: float
    avgRealtimeTtftMs: float
    avgTtsTtfbMs: float
    avgPlaybackLatencyMs: float
    avgTotalLatencyMs: float
    sampleCount: int
    dominantSource: str
    dominantLabel: str


class MetricsRules(TypedDict):
    passed: int
    partial: int
    failed: int
    checked: int


class MetricsSummary(TypedDict):
    totalCalls: int
    totalDuration: float
    totalCost: float
    successRate: float
    analysisCoverage: float
    answeredRate: float
    answeredCalls: int
    analyzedCalls: int
    pendingAnalysisCalls: int
    ruleCompliance: float
    totalInputTokens: float
    totalOutputTokens: float
    avgLatencyMs: float
    latencyBreakdown: LatencyBreakdown
    currency: Optional[str]
    rules: MetricsRules


class MetricsTrend(TypedDict):
    date: str
    calls: int
    cost: float
    success: int
    successAnalyzed: int
    analyzed: int
    inputTokens: float
    outputTokens: float
    avgLatencyMs: float
    latencySampleCount: int
    avgLatency: float
    latencyBreakdown: LatencyBreakdown
    successRate: float


class HourlyActivity(TypedDict):
    hour: int
    calls: int


class DurationDistribution(TypedDict):
    range: str
    count: int


class DisconnectReason(TypedDict):
    reason: str
    count: int


class SentimentMetric(TypedDict):
    name: str
    value: int
    color: str


class MetricsFunnel(TypedDict):
    initiated: int
    answered: int
    success: int


class TopAssistantMetric(TypedDict):
    id: str
    name: str
    calls: int
    answeredRate: float
    analysisCoverage: float
    successRate: float
    avgDuration: float
    totalCost: float
    avgCost: float
    totalInputTokens: float
    totalOutputTokens: float
    avgLatency: float
    latencyBreakdown: LatencyBreakdown
    ruleCompliance: float


class ToolUsageMetric(TypedDict):
    name: str
    count: int
    success: int
    fail: int


class MetricsResponse(TypedDict):
    summary: MetricsSummary
    trends: List[MetricsTrend]
    hourlyActivity: List[HourlyActivity]
    durationDistribution: List[DurationDistribution]
    disconnectReasons: List[DisconnectReason]
    sentimentAnalysis: List[SentimentMetric]
    funnel: MetricsFunnel
    topAssistants: List[TopAssistantMetric]
    toolUsage: List[ToolUsageMetric]


__all__ = [
    "AiDisclosure",
    "AiDisclosureLabel",
    "Assistant",
    "AssistantBackgroundAudio",
    "AssistantObjectResponse",
    "AssistantResponse",
    "AssistantStatus",
    "AssistantSttConfig",
    "AssistantSttResponseConfig",
    "AwsRuntimeTtsInput",
    "BackgroundAudioClip",
    "CallBackgroundAudio",
    "CallAnalysis",
    "CallLog",
    "CallLogHistoryEntry",
    "CallSttConfig",
    "CarrierResult",
    "ConversationConfig",
    "CreateAssistantFallbackResponse",
    "CreateAssistantParams",
    "CreateAssistantResponse",
    "CreateCallParams",
    "CreateCallResponse",
    "CreateLeadParams",
    "CreateLeadResponse",
    "CreateWebCallParams",
    "CreateWebCallResponse",
    "Customer",
    "DeleteAssistantResponse",
    "DefaultedRuntimeTtsInput",
    "DisconnectReason",
    "DurationDistribution",
    "GetCallLogResponse",
    "FullRuntimeTtsInput",
    "InlineTool",
    "HourlyActivity",
    "JSONScalar",
    "JSONObject",
    "JSONValue",
    "KeywordBoost",
    "LatencyBreakdown",
    "ListAssistantsResponse",
    "ListCallLogsResponse",
    "LlmConfig",
    "MetricsRange",
    "MetricsResponse",
    "MetricsFunnel",
    "MetricsRules",
    "MetricsSummary",
    "MetricsTrend",
    "PredefinedFunctionsConfig",
    "PrivacyConfig",
    "RecordingUrlResponse",
    "RuntimeLlmInput",
    "RuntimeLlmProvider",
    "RuntimeSttProvider",
    "RuntimeTtsInput",
    "RuntimeTtsProvider",
    "SentimentMetric",
    "SubscriptionLimits",
    "StructuredOutputResult",
    "TtsConfig",
    "ToolUsageMetric",
    "TopAssistantMetric",
    "UpdateAssistantFallbackResponse",
    "UpdateAssistantParams",
    "UpdateAssistantResponse",
    "WebCustomer",
]
