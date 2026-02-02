import { app } from "electron";
import { createTray } from "./windows/TrayManager.js";
import {
  startActionExecutor,
  killActionExecutor,
} from "./services/ActionExecutorService.js";
import { windowManager } from "./services/WindowManager.js";
import { registerAllHandlers } from "./ipc/index.js";

app.on("ready", async () => {
  console.log("App Ready - Initializing Application");

  // 1. Start Services
  startActionExecutor();

  // 2. Create Main Window via WindowManager
  const mainWindow = windowManager.createMainWindow();

  // 3. Register IPC Handlers
  registerAllHandlers(mainWindow);

  // 4. Create Tray
  createTray(mainWindow.getBrowserWindow());

  // 5. App level cleanup
  app.on("will-quit", () => {
    killActionExecutor();
  });
});
