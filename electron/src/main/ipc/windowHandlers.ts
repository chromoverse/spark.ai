import { ipcMainHandle, ipcMainOn } from "../utils/ipcUtils.js";
import { MainWindow } from "../windows/MainWindow.js";
import { windowManager } from "../services/WindowManager.js";
import type { IMediaDevice } from "@root/types";

export function registerWindowHandlers(mainWindow: MainWindow) {
  // Frame window actions (minimize, maximize, close)
  ipcMainOn("frameWindowAction", (payload) => {
    switch (payload) {
      case "MINIMIZE":
        mainWindow.minimize();
        break;
      case "MAXIMIZE":
        mainWindow.maximize();
        break;
      case "CLOSE":
        mainWindow.close();
        break;
    }
  });

  ipcMainHandle("isMainWindowMaximized", () =>
    mainWindow.getBrowserWindow().isMaximized(),
  );

  ipcMainHandle("getFrameState", () => {
    return mainWindow.getBrowserWindow().isMinimized()
      ? "MINIMIZE"
      : "MAXIMIZE";
  });

  // Authentication success handler - close main window and open secondary window
  ipcMainHandle("onAuthSuccess", async () => {
    console.log("Authentication successful - switching to AI Panel window");

    // Close the main window
    mainWindow.close();

    // Open the secondary window (AI Panel)
    windowManager.openSecondaryWindow();

    return { success: true };
  });

  // Authentication failure handler - show main window for login
  ipcMainHandle("onAuthFailure", async () => {
    console.log("Authentication failed/missing - showing Main window for login");
    mainWindow.getBrowserWindow().show();
    return { success: true };
  });

  // Media state sync from Renderer to Tray
  ipcMainHandle("updateMediaState", async (_event, payload: { 
    micOn?: boolean; 
    cameraOn?: boolean;
    audioInputs?: IMediaDevice[];
    videoInputs?: IMediaDevice[];
    selectedInputDeviceId?: string | null;
    selectedCameraDeviceId?: string | null;
  }) => {
    const { trayManager } = await import("../windows/TrayManager.js");
    trayManager.updateMediaState(payload);
    return payload;
  });
}
