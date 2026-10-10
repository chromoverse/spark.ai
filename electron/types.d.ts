import type { TaskRecord } from "./src/types/socket.types";

// types.d.ts

// FrameWindowAction
export type IFrameWindowAction = "CLOSE" | "MINIMIZE" | "MAXIMIZE";
export type IOnboardingWindowMode = "IMMERSIVE" | "MAXIMIZED" | "DEFAULT";

// Media Types handling
export type IMediaDeviceType = "audioinput" | "audiooutput" | "videoinput";

export interface IMediaDevice {
  deviceId: string;
  kind: IMediaDeviceType;
  label: string;
  groupId: string;
}

export interface IMediaDevices {
  audioInputs: IMediaDevice[];
  audioOutputs: IMediaDevice[];
  videoInputs: IMediaDevice[];
}

export interface IMediaPermissions {
  camera: boolean;
  microphone: boolean;
  speaker: boolean;
}

export interface IMediaStream {
  audioDeviceiId?: string;
  cameraDeviceiId?: string;
}

interface IActionExecutorResponseResults {
  taskId: string;
  success: boolean;
  data: Record<string, unknown>;
  error?: string;
  durationMs?: number;
}
export interface IActionExecutorResponse {
  status: string;
  results: Array<IActionExecutorResponseResults>;
  message: string;
}

export interface IDeviceUsageStatusManager {
  cpuUsage: number;
  ramUsage: number;
  storageData: { total: number; free: number; usage: number };
}

export interface ISocketConnectionState {
  connected: boolean;
  socketId?: string;
  reason?: string;
}

export interface ISocketEventForwardPayload {
  event: string;
  data: unknown;
}

// Brain v2 (docs/API.md). Tokens stay in the main process; the renderer only sees these.
export type IBrainStatus = "signed_out" | "connecting" | "connected" | "offline";

export interface IBrainUser {
  id: string;
  email: string;
  name: string | null;
}

export interface IBrainSettings {
  language: string;
  auto_detect_language: boolean;
  voice: string | null;
  verbosity: "brief" | "normal" | "detailed";
  address_as: string | null;
  permission_mode: "default" | "ask" | "trust";
  allow_training_providers: boolean;
  models: Record<string, unknown>;
}

export interface IBrainSession {
  user: IBrainUser & { nickname: string | null; plan: string };
  device_id: string;
  settings: IBrainSettings;
}

export type IBrainResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };

export interface IBrainEvent {
  event: string;
  data: unknown;
}

// Voice loop (R1): the body sidecar and what plays in the voice window.
export type IBodyStatus = "starting" | "ready" | "down" | "missing";

export type IVoiceEvent =
  | { kind: "audio"; uttId: string; seq: number; mime: string; data: string }
  | { kind: "done"; uttId: string; ok: boolean }
  | { kind: "cue"; cue: "heard" | "done" | "error"; signalId: string }
  | { kind: "stop" };

export interface IVoiceSendResult {
  signalId: string;
  tier: number | null;
  handled: boolean;
  error?: string;
}

export interface IEngineScore {
  engine: string;
  role: string;
  p50_ms: number | null;
  p95_ms: number | null;
  success: number;
  expressive: boolean;
  ewma_ms: number | null;
  accuracy?: number | null; // STT: 1 - word error rate on the probe clip
}

export interface IModelDownload {
  role: "wake" | "stt" | "tts";
  mb: number;
  pct: number;
  state: "downloading" | "ready" | "failed";
  error?: string;
}

/** What the ear heard at its endpoint candidate: `wake` false = no wake word (dropped on the
 * device), true = the wake word was in it (`heard` "" = only the wake word), null = no wake check
 * (follow-up or no model yet). Nothing runs until `voice.commit(signalId, heard)`. */
export interface IVoiceHeard {
  signalId: string;
  heard: string;
  wake: boolean | null;
}

export interface IEnginePlan {
  stt: string[];
  tts: string[];
  local_llm: string[];
  scores: Record<string, IEngineScore>;
  reasons?: Record<string, string>;
  history?: { ts: number; trigger: string; role: string; engine: string; p50_ms: number | null; p95_ms: number | null; success: number }[];
  budget_ms?: { tts: number; stt: number };
  models?: Record<string, IModelDownload>;
  wake?: boolean;
}

export interface IEnginesInfo {
  bodyStatus: IBodyStatus;
  plan: IEnginePlan | null;
}

export interface IMicControlPayload {
  action: "mute" | "unmute" | "toggle";
  source?: string;
}

// Payload Mapper - FIXED: Now includes parameters
export type IEventPayloadMapping = {
  frameWindowAction: IFrameWindowAction;
  getFrameState: IFrameWindowAction;
  isMainWindowMaximized: boolean;
  setOnboardingWindowMode: { success: boolean };
  openExternalUrl: { success: boolean };

  // Media
  getMediaDevices: IMediaDevices;
  getMediaPermissions: IMediaPermissions;
  checkMediaPermission: IMediaPermissions;
  requestMediaPermissions: IMediaPermissions;
  checkSystemPermissions: IMediaPermissions;
  startMediaStream: IMediaStream;
  stopMediaStream: void;

  // Device Usage Status
  getDeviceUsageStatus: IDeviceUsageStatusManager;
  poolDeviceStatus: void;

  // Task Execution
  executeTasks: IActionExecutorResponse;

  // Secondary Window
  openSecondaryWindow: void;
  resizeSecondaryWindow: void;
  closeAiPanelExpansion: void;

  // Tray Synchronization
  onTrayMediaToggle: { type: "MIC" | "CAMERA" };
  onTrayDeviceSelect: { type: "MIC" | "CAMERA"; deviceId: string };
  onMicMuteToggle: Record<string, never>; // Global shortcut for mic mute/unmute
  onMicControl: IMicControlPayload;
  sparkNavigate: { tab: string };
  updateMediaState: {
    micOn?: boolean;
    cameraOn?: boolean;
    audioInputs?: IMediaDevice[];
    videoInputs?: IMediaDevice[];
    selectedInputDeviceId?: string | null;
    selectedCameraDeviceId?: string | null;
  };

  // Authentication API
  onAuthSuccess: { success: boolean };
  onAuthFailure: { success: boolean };

  // Brain v2
  brainOtpStart: IBrainResult<{ sent: boolean }>;
  brainOtpVerify: IBrainResult<IBrainUser>;
  brainGoogleSignIn: IBrainResult<IBrainUser>;
  brainGetSession: IBrainResult<IBrainSession | null>;
  brainSignOut: IBrainResult<{ signedOut: boolean }>;
  brainGetStatus: IBrainStatus;
  brainStatus: IBrainStatus;
  brainEvent: IBrainEvent;

  // Voice loop (R1)
  voiceSend: IBrainResult<IVoiceSendResult>;
  voiceStop: IBrainResult<{ stopped: boolean }>;
  voiceHear: IBrainResult<IVoiceHeard>;
  voiceCommit: IBrainResult<IVoiceSendResult>;
  voiceDrop: { ok: boolean };
  voiceFirstAudio: { ok: boolean };
  voiceSpeaking: { ok: boolean };
  voiceSpeakingState: { speaking: boolean; at: number };
  enginesGet: IBrainResult<IEnginesInfo>;
  enginesBenchmark: IBrainResult<IEnginesInfo>;
  voiceEvent: IVoiceEvent;
  bodyStatus: IBodyStatus;
  enginePlan: IEnginePlan;

  // Socket IPC Bridge
  socketEmit: { success: boolean; error?: string };
  getSocketConnectionState: ISocketConnectionState;
  socketConnectionState: ISocketConnectionState;
  socketEventForward: ISocketEventForwardPayload;

  // File dialog
  showOpenFileDialog: { filePaths: string[]; canceled: boolean };
};

declare global {
  interface Window {
    // Older Chromium name, kept as a fallback for AudioContext.
    webkitAudioContext?: typeof AudioContext;
    electronApi: {
      sendFrameAction: (payload: IFrameWindowAction) => void;
      getFrameState: () => Promise<IFrameWindowAction>;
      isMainWindowMaximized: () => Promise<boolean>;
      setOnboardingWindowMode: (
        payload: IOnboardingWindowMode,
      ) => Promise<{ success: boolean }>;
      openExternalUrl: (url: string) => Promise<{ success: boolean }>;
      onWindowMaximizeStateChange: (
        callback: (payload: boolean) => void,
      ) => () => void;

      // Media APIs
      getMediaDevices: () => Promise<IMediaDevices>;
      getMediaPermissions: () => Promise<IMediaPermissions>;
      checkMediaPermission: () => Promise<IMediaPermissions>;
      requestMediaPermissions: () => Promise<IMediaPermissions>;
      checkSystemPermissions: () => Promise<IMediaPermissions>;

      // Device Usage Status APIs
      getDeviceUsageStatus: () => Promise<IDeviceUsageStatusManager>;
      onDeviceUsageStatusChange: (
        callback: (payload: IDeviceUsageStatusManager) => void,
      ) => () => void;

      // Python Automation API -  as SQH Listener
      executeTasks: (tasks: TaskRecord[]) => Promise<IActionExecutorResponse>;

      // Secondary Window API
      openSecondaryWindow: () => Promise<void>;
      resizeSecondaryWindow: (width: number, height: number) => Promise<void>;
      onCloseAiPanelExpansion: (callback: () => void) => () => void;

      // Tray Synchronization
      updateMediaState: (state: {
        micOn?: boolean;
        cameraOn?: boolean;
        audioInputs?: IMediaDevice[];
        videoInputs?: IMediaDevice[];
        selectedInputDeviceId?: string | null;
        selectedCameraDeviceId?: string | null;
      }) => Promise<void>;
      onTrayMediaToggle: (
        callback: (payload: { type: "MIC" | "CAMERA" }) => void,
      ) => () => void;
      onTrayDeviceSelect: (
        callback: (payload: {
          type: "MIC" | "CAMERA";
          deviceId: string;
        }) => void,
      ) => () => void;
      // Global shortcut for mic mute/unmute
      onMicMuteToggle: (callback: () => void) => () => void;
      onMicControl: (
        callback: (payload: IMicControlPayload) => void,
      ) => () => void;
      onSparkNavigate: (
        callback: (payload: { tab: string }) => void,
      ) => () => void;

      // Authentication API
      onAuthSuccess: () => Promise<{ success: boolean }>;
      onAuthFailure: () => Promise<{ success: boolean }>;

      // Brain v2: sign-in, session, live connection
      brain: {
        otpStart: (email: string) => Promise<IBrainResult<{ sent: boolean }>>;
        otpVerify: (email: string, code: string) => Promise<IBrainResult<IBrainUser>>;
        googleSignIn: () => Promise<IBrainResult<IBrainUser>>;
        getSession: () => Promise<IBrainResult<IBrainSession | null>>;
        signOut: () => Promise<IBrainResult<{ signedOut: boolean }>>;
        getStatus: () => Promise<IBrainStatus>;
        onStatus: (callback: (status: IBrainStatus) => void) => () => void;
        onEvent: (callback: (event: IBrainEvent) => void) => () => void;
      };
      // Voice loop (R1): tier 0 on the device, then the brain; audio plays in one window
      voice: {
        send: (text: string) => Promise<IBrainResult<IVoiceSendResult>>;
        stop: () => Promise<IBrainResult<{ stopped: boolean }>>;
        hear: (pcm16: string, endedAt: number, wake: boolean) => Promise<IBrainResult<IVoiceHeard>>;
        commit: (signalId: string, text: string) => Promise<IBrainResult<IVoiceSendResult>>;
        drop: (signalId: string) => Promise<{ ok: boolean }>;
        firstAudio: (signalId: string, at: number) => Promise<{ ok: boolean }>;
        speaking: (speaking: boolean) => Promise<{ ok: boolean }>;
        onSpeaking: (callback: (state: { speaking: boolean; at: number }) => void) => () => void;
        onEvent: (callback: (event: IVoiceEvent) => void) => () => void;
      };
      engines: {
        get: () => Promise<IBrainResult<IEnginesInfo>>;
        runBenchmark: () => Promise<IBrainResult<IEnginesInfo>>;
        onPlan: (callback: (plan: IEnginePlan) => void) => () => void;
        onBodyStatus: (callback: (status: IBodyStatus) => void) => () => void;
      };

      // Socket IPC Bridge
      socketEmit: (
        event: string,
        ...args: unknown[]
      ) => Promise<{ success: boolean; error?: string }>;
      getSocketConnectionState: () => Promise<ISocketConnectionState>;
      onSocketConnectionState: (
        callback: (payload: ISocketConnectionState) => void,
      ) => () => void;
      onSocketEventForward: (
        callback: (payload: ISocketEventForwardPayload) => void,
      ) => () => void;

      // File dialog
      showOpenFileDialog: () => Promise<{ filePaths: string[]; canceled: boolean }>;
    };
  }
}
