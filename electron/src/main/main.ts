import { app, globalShortcut, BrowserWindow } from "electron";

// Only `electron` loads before `ready`. On Electron 39.2, touching Node's lazy WebSocket
// (`globalThis.WebSocket`, `http.WebSocket`; socket.io-client and `import http` both do) before
// `ready` kills the main process with EXCEPTION_BREAKPOINT. App modules are imported after `ready`.
type WindowManager = typeof import("./services/WindowManager.js").windowManager;
type IpcWebContentSend = typeof import("./utils/ipcUtils.js").ipcWebContentSend;

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

function registerGlobalShortcuts(
  mainWindow: BrowserWindow,
  windowManager: WindowManager,
  ipcWebContentSend: IpcWebContentSend,
) {
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

// No top-level await here: Electron fires `ready` only after this entry module finishes evaluating.
void app.whenReady().then(async () => {
  console.log("App Ready - Initializing Application");

  // 1. Load app modules (in the old static-import order)
  const { trayManager } = await import("./windows/TrayManager.js");
  const { windowManager } = await import("./services/WindowManager.js");
  const { registerAllHandlers } = await import("./ipc/index.js");
  const { ipcWebContentSend } = await import("./utils/ipcUtils.js");

  // 2. Create Main Window via WindowManager
  const mainWindow = windowManager.createMainWindow();
  const browserWindow = mainWindow.getBrowserWindow();

  // 3. Register IPC Handlers
  registerAllHandlers(mainWindow);

  // 4. Create Tray
  trayManager.init(browserWindow);

  // 5. Register Global Shortcuts
  registerGlobalShortcuts(browserWindow, windowManager, ipcWebContentSend);

  // Socket connection is initialized lazily from onAuthSuccess.
}).catch((err: unknown) => {
  // Never silent: a startup failure must not leave a windowless app running.
  console.error("[startup] failed", err);
  app.exit(1);
});
