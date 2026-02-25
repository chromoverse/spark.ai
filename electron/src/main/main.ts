import { app } from "electron";
import { trayManager } from "./windows/TrayManager.js";
import { windowManager } from "./services/WindowManager.js";
import { registerAllHandlers } from "./ipc/index.js";

app.on("ready", async () => {
  console.log("App Ready - Initializing Application");


  // 2. Create Main Window via WindowManager
  const mainWindow = windowManager.createMainWindow();

  // 3. Register IPC Handlers
  registerAllHandlers(mainWindow);

  // 4. Create Tray
  trayManager.init(mainWindow.getBrowserWindow());
});
