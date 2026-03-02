// types.d.ts

// FrameWindowAction
export type IFrameWindowAction = "CLOSE" | "MINIMIZE" | "MAXIMIZE";

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
  data: Record<string, any>;
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

// Payload Mapper - FIXED: Now includes parameters
export type IEventPayloadMapping = {
  frameWindowAction: IFrameWindowAction;
  getFrameState: IFrameWindowAction;
  isMainWindowMaximized: boolean;

  // Media
  getMediaDevices: IMediaDevices;
  getMediaPermissions: IMediaPermissions;
  checkMediaPermission: IMediaPermissions;
  requestMediaPermissions: IMediaPermissions;
  checkSystemPermissions: IMediaPermissions;
  startMediaStream: IMediaStream;
  stopMediaStream: void;

  // Token Management
  saveToken: void;
  getToken: string | null;
  deleteToken: void;

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

  // Socket IPC Bridge
  socketEmit: { success: boolean; error?: string };
  getSocketConnectionState: ISocketConnectionState;
  socketConnectionState: ISocketConnectionState;
  socketEventForward: ISocketEventForwardPayload;
};

declare global {
  interface Window {
    electronApi: {
      sendFrameAction: (payload: IFrameWindowAction) => void;
      getFrameState: () => Promise<IFrameWindowAction>;
      isMainWindowMaximized: () => Promise<boolean>;
      onWindowMaximizeStateChange: (
        callback: (payload: boolean) => void,
      ) => () => void;

      // Media APIs
      getMediaDevices: () => Promise<IMediaDevices>;
      getMediaPermissions: () => Promise<IMediaPermissions>;
      checkMediaPermission: () => Promise<IMediaPermissions>;
      requestMediaPermissions: () => Promise<IMediaPermissions>;
      checkSystemPermissions: () => Promise<IMediaPermissions>;

      // token management APIs
      saveToken: (ACCOUNT_NAME: string, token: string) => Promise<void>;
      getToken: (ACCOUNT_NAME: string) => Promise<string | null>;
      deleteToken: (ACCOUNT_NAME: string) => Promise<void>;

      // Device Usage Status APIs
      getDeviceUsageStatus: () => Promise<IDeviceUsageStatusManager>;
      onDeviceUsageStatusChange: (
        callback: (payload: IDeviceUsageStatusManager) => void,
      ) => () => void;

      // Python Automation API -  as SQH Listener
      executeTasks: (tasks: any[]) => Promise<IActionExecutorResponse>;

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

      // Authentication API
      onAuthSuccess: () => Promise<{ success: boolean }>;
      onAuthFailure: () => Promise<{ success: boolean }>;

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
    };
  }
}
