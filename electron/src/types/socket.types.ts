// src/types/socket.types.ts

// ========================================
// RE-EXPORT TASK TYPES FROM AGENTIC.TYPES
// ========================================
// These types are defined in agentic.types.ts to avoid duplication

import type {
  ExecutionTarget,
  FailurePolicy,
  TaskStatus,
  LifecycleMessages,
  TaskControl,
  Task,
  TaskOutput,
  TaskRecord,
} from "./agentic.types.js";

// Re-export for external use
export type {
  ExecutionTarget,
  FailurePolicy,
  TaskStatus,
  LifecycleMessages,
  TaskControl,
  Task,
  TaskOutput,
  TaskRecord,
};

// ========================================
// PQH (PRIMARY QUERY HANDLER) TYPES
// ========================================

export interface ICognitiveState {
  userQuery: string;
  emotion: string;
  thoughtProcess: string;
  answer: string;
  answerEnglish: string;
}

export interface QueryResultPayload {
  requestId: string;
  cognitiveState: ICognitiveState;
  requestedTool: string[];
}

// ========================================
// WEBSOCKET EVENT TYPES
// ========================================

export interface UserQueryPayload {
  audio: ArrayBuffer | string;
  mimeType: string;
  timestamp: number;
  duration?: number;
  userId?: string;
  sessionId?: string;
}

// Streaming STT payloads
export interface UserSpeakingPayload {
  audio: ArrayBuffer | string; // raw binary (preferred) or base64 fallback
  mimeType: string;
  sessionId: string;
  seq: number;
  timestamp: number;
}

export interface UserStopSpeakingPayload {
  sessionId: string;
  timestamp: number;
}

export interface UserInterruptPayload {
  timestamp: number;
}

export interface UserSpeechStartedPayload {
  sessionId: string;
  timestamp: number;
}

export interface TTSPayload {
  text: string | undefined;
  userId: string;
  voice?: string;
}

export interface RegisteredPayload {
  userId: string;
  socketId?: string;
}

export interface TranscriptionPayload {
  text: string;
  confidence: number;
  duration: number;
  timestamp: number;
}

export interface AIStartPayload {
  requestId: string;
}

export interface AITokenPayload {
  requestId: string;
  token: string;
}

export interface AIEndPayload {
  requestId: string;
  success: boolean;
  error?: string;
}

export interface LatencyMetricsPayload {
  requestId: string;
  success: boolean;
  sttReadyMs?: number | null;
  speechToFirstTtsMs?: number | null;
  firstLlmTokenMs?: number | null;
  firstTtsDispatchMs?: number | null;
  contextMs?: number | null;
  totalMs?: number | null;
  emittedChunks?: number;
  chars?: number;
  error?: string;
}

export interface SendMessagePayload {
  senderId: string;
  receiverId: string;
  content: string;
  timestamp?: number;
}

export interface ErrorPayload {
  code: string;
  message: string;
  timestamp: number;
  details?: any;
}

export type ServerStatusFlag = "INFO" | "WARN" | "ERROR";

export interface ServerStatus {
  status: string;
  timestamp: string;
  flag: ServerStatusFlag;
}

// Task execution payload - unified format (server always sends tasks array)
export interface TaskExecuteBatchPayload {
  userId: string;
  tasks: TaskRecord[];
}

export interface TaskResultPayload {
  userId: string;
  taskId: string;
  result: TaskOutput;
}

export interface TaskBatchResultsPayload {
  userId: string;
  results: Array<{
    taskId: string;
    result: TaskOutput;
  }>;
}

export interface TaskStatusPayload {
  taskId: string;
  status: TaskStatus;
}

export interface TaskProgressPayload {
  userId: string;
  summary: Record<string, number | string>;
}

// ========================================
// SOCKET EVENT INTERFACE
// ========================================

export interface SocketEvents {
  // ========= Client → Server Events =========
  register_user: (userId: string) => void;
  "send-user-voice-query": (data: UserQueryPayload) => void;
  "send-user-text-query": (query: string) => void;
  "user-speaking": (data: UserSpeakingPayload) => void;
  "user-stop-speaking": (data: UserStopSpeakingPayload) => void;
  "user-interrupt": (data: UserInterruptPayload) => void;
  "user-speech-started": (data: UserSpeechStartedPayload) => void;
  "request-tts": (data: TTSPayload) => void;
  "test-ws": (data?: any) => void;
  
  // Task execution results (client → server)
  "task:result": (data: TaskResultPayload) => void;
  "task:batch_results": (data: TaskBatchResultsPayload) => void;

  // ========= Server → Client Events =========
  registered: (data: RegisteredPayload) => void;
  
  // PQH responses
  "query-result": (data: QueryResultPayload) => void;
  "query-error": (data: any) => void;
  
  // Task orchestration (SQH) - both events use same payload format
  "task:execute": (data: TaskExecuteBatchPayload) => void;
  "task:execute_batch": (data: TaskExecuteBatchPayload) => void;
  "task:status": (data: TaskStatusPayload) => void;
  "task:progress": (data: TaskProgressPayload) => void;
  "task:summary": (data: TaskProgressPayload) => void;
  
  // TTS events (payloads carry a streamId for per-stream tracking)
  "tts-start": (payload: { streamId: string; text?: string }) => void;
  "tts-chunk": (payload: { streamId: string; data: ArrayBuffer }) => void;
  "tts-end": (payload: { streamId: string; success: boolean; chunks?: number; error?: string }) => void;
  "tts-interrupt": () => void;
  "response-tts": (res: { success?: boolean; error?: string }) => void;
  
  // Transcription
  "transcription-result": (data: TranscriptionPayload) => void;

  // Stream lifecycle events for conversational UI lock/token rendering
  "ai-start": (data: AIStartPayload) => void;
  "ai-token": (data: AITokenPayload) => void;
  "ai-end": (data: AIEndPayload) => void;
  "latency-metrics": (data: LatencyMetricsPayload) => void;
  
  // Server status
  "server-status": (data: ServerStatus) => void;
  processing: (data: any) => void;
  
  // Generic events
  error: (error: ErrorPayload) => void;
  connect: () => void;
  disconnect: (reason: string) => void;
  connect_error: (error: Error) => void;
  reconnect: (attemptNumber: number) => void;
}

// ========================================
// HELPER TYPE EXPORTS
// ========================================

export type SocketEventName = keyof SocketEvents;
export type SocketEventHandler<T extends SocketEventName> = SocketEvents[T];
