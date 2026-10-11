import { BrowserWindow } from "electron";
import { ipcMainHandle } from "../utils/ipcUtils.js";
import { 
  getMediaDevices, 
  checkMediaPermissions, 
  requestMediaPermissions
} from "../services/MediaManager.js";

export function registerMediaHandlers(mainWindow: BrowserWindow) {
  ipcMainHandle("getMediaDevices", () => getMediaDevices(mainWindow));
  ipcMainHandle("checkMediaPermission", () => checkMediaPermissions(mainWindow));
  ipcMainHandle("requestMediaPermissions", () => requestMediaPermissions(mainWindow));
}
