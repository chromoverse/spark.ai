import { app, globalShortcut, BrowserWindow } from "electron";
import { trayManager } from "./windows/TrayManager.js";
import { windowManager } from "./services/WindowManager.js";
import { registerAllHandlers } from "./ipc/index.js";
import { ipcWebContentSend } from "./utils/ipcUtils.js";

const SAFE_GPU_MODE_ARG = "--safe-gpu-mode";
const safeGpuModeEnabled =
  process.argv.includes(SAFE_GPU_MODE_ARG) || process.env.ELECTRON_SAFE_GPU_MODE === "1";

if (safeGpuModeEnabled) {
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch("disable-gpu");
  console.warn("[GPU] Safe mode enabled: hardware acceleration disabled.");
}

let hasTriggeredGpuRelaunch = false;

function setupGpuRecovery() {
  app.on("child-process-gone", (_event, details) => {
    if (details.type !== "GPU") {
      return;
    }

    console.error(
      `[GPU] Child process gone: reason=${details.reason}, exitCode=${details.exitCode}, service=${details.serviceName ?? details.name ?? "unknown"}`,
    );

    const shouldRelaunchInSafeMode =
      !safeGpuModeEnabled &&
      !hasTriggeredGpuRelaunch &&
      details.reason !== "clean-exit";

    if (!shouldRelaunchInSafeMode) {
      return;
    }

    hasTriggeredGpuRelaunch = true;
    console.warn(`[GPU] Relaunching app with ${SAFE_GPU_MODE_ARG}.`);

    const args = process.argv.slice(1);
    if (!args.includes(SAFE_GPU_MODE_ARG)) {
      args.push(SAFE_GPU_MODE_ARG);
    }

    app.relaunch({ args });
    app.exit(0);
  });

  app.on("gpu-info-update", () => {
    console.log("[GPU] Feature status", app.getGPUFeatureStatus());
  });
}

function registerGlobalShortcuts(mainWindow: BrowserWindow) {
  // Register Ctrl/Cmd + Shift + M for mic mute/unmute toggle
  const shortcut =
    process.platform === "darwin" ? "CommandOrControl+Shift+M" : "Ctrl+Shift+M";

  const registered = globalShortcut.register(shortcut, () => {
    console.log("🔇 Global shortcut triggered: Toggle Microphone Mute");

    // Broadcast mic toggle to every open renderer window.
    // Each window has its own Redux store, so single-target emit can desync UI state.
    const secondaryWin = windowManager.getSecondaryWindow()?.getBrowserWindow();
    const targets = [mainWindow, secondaryWin].filter(
      (win): win is BrowserWindow => Boolean(win && !win.isDestroyed()),
    );

    for (const targetWindow of targets) {
      ipcWebContentSend("onMicMuteToggle", targetWindow.webContents, {});
    }
  });

  if (registered) {
    console.log(`✅ Global shortcut ${shortcut} registered for mic toggle`);
  } else {
    console.error(`❌ Failed to register global shortcut ${shortcut}`);
  }
}

setupGpuRecovery();

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
