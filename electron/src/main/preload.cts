import { contextBridge, ipcRenderer } from "electron";
import type {
  IEventPayloadMapping,
  IFrameWindowAction,
  IMicControlPayload,
  IBrainEvent,
  IBrainStatus,
  IBodyStatus,
  IEnginePlan,
  IVoiceEvent,
  IVoiceUserSaid,
} from "@root/types";

(() => {
  console.log("Preload Loaded");
})();

contextBridge.exposeInMainWorld("electronApi", {
  //frameWindowAction Apis
  sendFrameAction: (payload: IFrameWindowAction) =>
    ipcSend("frameWindowAction", payload),
  isMainWindowMaximized: () => ipcInvoke("isMainWindowMaximized", {}),
  openExternalUrl: (url: string) => ipcInvoke("openExternalUrl", url),
  onWindowMaximizeStateChange: (callback: (payload: boolean) => void) =>
    ipcOn("isMainWindowMaximized", callback),

  //media APIs
  getMediaDevices: () => ipcInvoke("getMediaDevices"),
  checkMediaPermission: () => ipcInvoke("checkMediaPermission"),
  requestMediaPermissions: () => ipcInvoke("requestMediaPermissions"),

  //Secondary Window API
  overlayInteractive: (on: boolean) => ipcInvoke("overlayInteractive", on),
  openMainWindow: () => ipcInvoke("openMainWindow"),

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
    approve: (approvalId: string, decision: "allow" | "deny" | "always") =>
      ipcInvoke("brainApprove", { approvalId, decision }),
    answer: (askId: string, answer: string) => ipcInvoke("brainAnswer", { askId, answer }),
    cancelJob: (jobId: string) => ipcInvoke("brainJobCancel", { jobId }),
    jobs: () => ipcInvoke("brainJobs"),
    request: (method: "GET" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown) =>
      ipcInvoke("brainRequest", { method, path, body }),
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
    onUserSaid: (callback: (line: IVoiceUserSaid) => void) => ipcOn("voiceUserSaid", callback),
    toggleEar: () => ipcInvoke("voiceEarToggle"),
    earSet: (listening: boolean) => ipcInvoke("voiceEarSet", { listening }),
    earGet: () => ipcInvoke("voiceEarGet"),
    onEarState: (callback: (state: { listening: boolean }) => void) => ipcOn("voiceEarState", callback),
  },
  engines: {
    get: () => ipcInvoke("enginesGet"),
    runBenchmark: () => ipcInvoke("enginesBenchmark"),
    onPlan: (callback: (plan: IEnginePlan) => void) => ipcOn("enginePlan", callback),
    onBodyStatus: (callback: (status: IBodyStatus) => void) => ipcOn("bodyStatus", callback),
  },


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
