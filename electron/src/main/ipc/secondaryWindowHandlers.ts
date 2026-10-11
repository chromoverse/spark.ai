import { ipcMainHandle } from "../utils/ipcUtils.js";
import { windowManager } from "../services/WindowManager.js";

export function registerSecondaryWindowHandlers() {
  ipcMainHandle("overlayInteractive", (_event, raw) => {
    windowManager.getSecondaryWindow()?.setInteractive(raw === true);
  });

  ipcMainHandle("openMainWindow", () => {
    const win = windowManager.getMainWindow().getBrowserWindow();
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
}
