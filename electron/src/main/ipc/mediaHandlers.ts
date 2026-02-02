import { BrowserWindow } from "electron";
import { ipcMainHandle } from "../utils/ipcUtils.js";
import { 
  getMediaPermissions, 
  getMediaDevices, 
  checkMediaPermissions, 
  requestMediaPermissions, 
  checkSystemPermissions 
} from "../services/MediaManager.js";

export function registerMediaHandlers(mainWindow: BrowserWindow) {
  ipcMainHandle("getMediaPermissions", () => getMediaPermissions(mainWindow));
  ipcMainHandle("getMediaDevices", () => getMediaDevices(mainWindow));
  ipcMainHandle("checkMediaPermission", () => checkMediaPermissions(mainWindow));
  ipcMainHandle("requestMediaPermissions", () => requestMediaPermissions(mainWindow));
  ipcMainHandle("checkSystemPermissions", () => checkSystemPermissions());
}
