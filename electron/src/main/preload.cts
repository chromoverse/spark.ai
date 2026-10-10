import { contextBridge, ipcRenderer } from "electron";
import type {
  IEventPayloadMapping,
  IFrameWindowAction,
  IOnboardingWindowMode,
  IDeviceUsageStatusManager,
  IMicControlPayload,
  ISocketConnectionState,
  ISocketEventForwardPayload,
  IBrainEvent,
  IBrainStatus,
  IBodyStatus,
  IEnginePlan,
  IVoiceEvent,
} from "@root/types";
import type { TaskRecord } from "@shared/socket.types.js";

(() => {
  console.log("Preload Loaded");
})();

contextBridge.exposeInMainWorld("electronApi", {
  //frameWindowAction Apis
  sendFrameAction: (payload: IFrameWindowAction) =>
    ipcSend("frameWindowAction", payload),
  getFrameState: () => ipcInvoke("getFrameState", {}),
  isMainWindowMaximized: () => ipcInvoke("isMainWindowMaximized", {}),
  setOnboardingWindowMode: (payload: IOnboardingWindowMode) =>
    ipcInvoke("setOnboardingWindowMode", payload),
  openExternalUrl: (url: string) => ipcInvoke("openExternalUrl", url),
  onWindowMaximizeStateChange: (callback: (payload: boolean) => void) =>
    ipcOn("isMainWindowMaximized", callback),

  //media APIs
  getMediaDevices: () => ipcInvoke("getMediaDevices"),
  getMediaPermissions: () => ipcInvoke("getMediaPermissions"),
  checkMediaPermission: () => ipcInvoke("checkMediaPermission"),
  requestMediaPermissions: () => ipcInvoke("requestMediaPermissions"),
  checkSystemPermissions: () => ipcInvoke("checkSystemPermissions"),

  //Device Usage Status APIs
  getDeviceUsageStatus: () => ipcInvoke("getDeviceUsageStatus"),
  onDeviceUsageStatusChange: (
    callback: (payload: IDeviceUsageStatusManager) => void,
  ) => ipcOn("getDeviceUsageStatus", callback),

  //python Automation API
  executeTasks: (payload: TaskRecord[]) => ipcInvoke("executeTasks", payload),

  //Secondary Window API
  openSecondaryWindow: () => ipcInvoke("openSecondaryWindow"),
  resizeSecondaryWindow: (width: number, height: number) =>
    ipcInvoke("resizeSecondaryWindow", { width, height }),
  onCloseAiPanelExpansion: (callback: () => void) =>
    ipcOn("closeAiPanelExpansion", callback),

  // Tray API
  updateMediaState: async (state) => {
    await ipcInvoke("updateMediaState", state);
  },
  onTrayMediaToggle: (
    callback: (payload: { type: "MIC" | "CAMERA" }) => void,
  ) => ipcOn("onTrayMediaToggle", callback),
  onTrayDeviceSelect: (
    callback: (payload: { type: "MIC" | "CAMERA"; deviceId: string }) => void,
  ) => ipcOn("onTrayDeviceSelect", callback),
  onMicMuteToggle: (callback: () => void) => ipcOn("onMicMuteToggle", callback),
  onMicControl: (callback: (payload: IMicControlPayload) => void) =>
    ipcOn("onMicControl", callback),
  onSparkNavigate: (callback: (payload: { tab: string }) => void) =>
    ipcOn("sparkNavigate", callback),

  //Authentication API
  onAuthSuccess: () => ipcInvoke("onAuthSuccess"),
  onAuthFailure: () => ipcInvoke("onAuthFailure"),

  brain: {
    otpStart: (email: string) => ipcInvoke("brainOtpStart", { email }),
    otpVerify: (email: string, code: string) => ipcInvoke("brainOtpVerify", { email, code }),
    googleSignIn: () => ipcInvoke("brainGoogleSignIn"),
    getSession: () => ipcInvoke("brainGetSession"),
    signOut: () => ipcInvoke("brainSignOut"),
    getStatus: () => ipcInvoke("brainGetStatus"),
    onStatus: (callback: (status: IBrainStatus) => void) => ipcOn("brainStatus", callback),
    onEvent: (callback: (event: IBrainEvent) => void) => ipcOn("brainEvent", callback),
  },

  voice: {
    send: (text: string) => ipcInvoke("voiceSend", { text }),
    stop: () => ipcInvoke("voiceStop"),
    hear: (pcm16: string, endedAt: number, wake: boolean) => ipcInvoke("voiceHear", { pcm16, endedAt, wake }),
    commit: (signalId: string, text: string) => ipcInvoke("voiceCommit", { signalId, text }),
    drop: (signalId: string) => ipcInvoke("voiceDrop", { signalId }),
    firstAudio: (signalId: string, at: number) => ipcInvoke("voiceFirstAudio", { signalId, at }),
    speaking: (speaking: boolean) => ipcInvoke("voiceSpeaking", { speaking }),
    onSpeaking: (callback: (state: { speaking: boolean; at: number; asked?: boolean }) => void) =>
      ipcOn("voiceSpeakingState", callback),
    onEvent: (callback: (event: IVoiceEvent) => void) => ipcOn("voiceEvent", callback),
  },
  engines: {
    get: () => ipcInvoke("enginesGet"),
    runBenchmark: () => ipcInvoke("enginesBenchmark"),
    onPlan: (callback: (plan: IEnginePlan) => void) => ipcOn("enginePlan", callback),
    onBodyStatus: (callback: (status: IBodyStatus) => void) => ipcOn("bodyStatus", callback),
  },

  // File dialog
  showOpenFileDialog: () => ipcInvoke("showOpenFileDialog"),

  // Socket IPC Bridge
  socketEmit: (event: string, ...args: unknown[]) =>
    ipcInvoke("socketEmit", { event, args }),
  getSocketConnectionState: () => ipcInvoke("getSocketConnectionState"),
  onSocketConnectionState: (callback: (payload: ISocketConnectionState) => void) =>
    ipcOn("socketConnectionState", callback),
  onSocketEventForward: (callback: (payload: ISocketEventForwardPayload) => void) =>
    ipcOn("socketEventForward", callback),
} satisfies Window["electronApi"]);

// ipc-preload-utils
function ipcInvoke<Key extends keyof IEventPayloadMapping>(
  key: Key,
  payload?: any,
): Promise<IEventPayloadMapping[Key]> {
  return ipcRenderer.invoke(key, payload);
}

function ipcOn<Key extends keyof IEventPayloadMapping>(
  key: Key,
  callback: (payload: IEventPayloadMapping[Key]) => void,
) {
  //cbfun callbackFunction
  const cbfun = (_event: any, payload: IEventPayloadMapping[Key]) =>
    callback(payload);
  ipcRenderer.on(key, cbfun);
  return () => ipcRenderer.off(key, cbfun);
}

function ipcSend<Key extends keyof IEventPayloadMapping>(
  key: Key,
  payload: IEventPayloadMapping[Key],
) {
  ipcRenderer.send(key, payload);
}
