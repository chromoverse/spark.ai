import { app, globalShortcut, BrowserWindow } from "electron";
import { trayManager } from "./windows/TrayManager.js";
import { windowManager } from "./services/WindowManager.js";
import { registerAllHandlers } from "./ipc/index.js";
import { ipcWebContentSend } from "./utils/ipcUtils.js";

function registerGlobalShortcuts(mainWindow: BrowserWindow) {
  // Register Ctrl/Cmd + Shift + M for mic mute/unmute toggle
  const shortcut =
    process.platform === "darwin" ? "CommandOrControl+Shift+M" : "Ctrl+Shift+M";

  const registered = globalShortcut.register(shortcut, () => {
    console.log("🔇 Global shortcut triggered: Toggle Microphone Mute");

    // Send the mic toggle event to the renderer
    const secondaryWin = windowManager.getSecondaryWindow()?.getBrowserWindow();
    const targetWindow = secondaryWin?.isVisible() ? secondaryWin : mainWindow;

    if (targetWindow) {
      ipcWebContentSend("onMicMuteToggle", targetWindow.webContents, {});
    }
  });

  if (registered) {
    console.log(`✅ Global shortcut ${shortcut} registered for mic toggle`);
  } else {
    console.error(`❌ Failed to register global shortcut ${shortcut}`);
  }
}

void app.whenReady().then(async () => {
  console.log("App Ready - Initializing Application");

  // 2. Create Main Window via WindowManager
  const mainWindow = windowManager.createMainWindow();
  const browserWindow = mainWindow.getBrowserWindow();

  // 3. Register IPC Handlers
  registerAllHandlers(mainWindow);

  // 4. Create Tray
  trayManager.init(browserWindow);

  // 5. Register Global Shortcuts
  registerGlobalShortcuts(browserWindow);

  // Socket connection is initialized lazily from onAuthSuccess.
});
