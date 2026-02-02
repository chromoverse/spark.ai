import { ipcMainHandle, ipcMainOn } from "../utils/ipcUtils.js";
import { MainWindow } from "../windows/MainWindow.js";

export function registerWindowHandlers(mainWindow: MainWindow) {
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

  ipcMainHandle("isMainWindowMaximized", () => mainWindow.getBrowserWindow().isMaximized());

  ipcMainHandle("getFrameState", () => {
    return mainWindow.getBrowserWindow().isMinimized() ? "MINIMIZE" : "MAXIMIZE";
  });
}
