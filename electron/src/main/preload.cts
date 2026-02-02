import { contextBridge, ipcRenderer } from "electron";
import { IEventPayloadMapping, IFrameWindowAction, IDeviceUsageStatusManager } from "@root/types";
import type { TaskRecord } from "@shared/socket.types.js";

(() => {
  console.log("Preload Loaded");
})()

contextBridge.exposeInMainWorld("electronApi", {
  //frameWindowAction Apis
  sendFrameAction: (payload: IFrameWindowAction) => ipcSend("frameWindowAction", payload),
  getFrameState: () => ipcInvoke("getFrameState", {}),
  isMainWindowMaximized: () => ipcInvoke("isMainWindowMaximized", {}),
  onWindowMaximizeStateChange: (callback: (payload: boolean) => void) => ipcOn("isMainWindowMaximized", callback),
  
  //media APIs
  getMediaDevices: () => ipcInvoke("getMediaDevices"),
  getMediaPermissions: () => ipcInvoke("getMediaPermissions"),
  checkMediaPermission: () => ipcInvoke("checkMediaPermission"),
  requestMediaPermissions: () => ipcInvoke("requestMediaPermissions"),
  checkSystemPermissions: () => ipcInvoke("checkSystemPermissions"),

  //token Management APIs
  saveToken: (ACCOUNT_NAME: string, token: string) => ipcInvoke("saveToken", { ACCOUNT_NAME, token }),
  getToken: (ACCOUNT_NAME: string) => ipcInvoke("getToken", { ACCOUNT_NAME }),
  deleteToken: (ACCOUNT_NAME: string) => ipcInvoke("deleteToken", { ACCOUNT_NAME }),

  //Device Usage Status APIs
  getDeviceUsageStatus: () => ipcInvoke("getDeviceUsageStatus"),
  onDeviceUsageStatusChange: (callback : (payload:IDeviceUsageStatusManager ) => void) => ipcOn("getDeviceUsageStatus", callback),

  //python Automation API
  executeTasks: (payload: TaskRecord[]) => ipcInvoke("executeTasks", payload),

  //Secondary Window API
  openSecondaryWindow: () => ipcInvoke("openSecondaryWindow"),
  resizeSecondaryWindow: (width: number, height: number) => ipcInvoke("resizeSecondaryWindow", { width, height }),
  onCloseAiPanelExpansion: (callback: () => void) => ipcOn("closeAiPanelExpansion", callback),

} satisfies Window["electronApi"]);


// ipc-preload-utils
function ipcInvoke<Key extends keyof IEventPayloadMapping>(
  key: Key,
  payload?: any
): Promise<IEventPayloadMapping[Key]> {
  return ipcRenderer.invoke(key, payload);
}

function ipcOn<Key extends keyof IEventPayloadMapping>(
  key: Key,
  callback: (payload: IEventPayloadMapping[Key]) => void
) {
  //cbfun callbackFunction
  const cbfun = (_event: any, payload: IEventPayloadMapping[Key]) =>
    callback(payload);
  ipcRenderer.on(key, cbfun);
  return () => ipcRenderer.off(key, cbfun);
}

function ipcSend<Key extends keyof IEventPayloadMapping>(
  key: Key,
  payload: IEventPayloadMapping[Key]
) {
  ipcRenderer.send(key, payload);
}