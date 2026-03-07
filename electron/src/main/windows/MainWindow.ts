import { BrowserWindow, app } from "electron";
import * as path from "node:path";
import { getPreloadPath } from "../utils/pathResolver.js";
import { isDevMode } from "../utils/isDevMode.js";
import { ipcWebContentSend } from "../utils/ipcUtils.js";
import type { Rectangle } from "electron";

export class MainWindow {
  private window: BrowserWindow | null = null;
  private onboardingWindowSnapshot: {
    bounds: Rectangle;
    wasMaximized: boolean;
  } | null = null;

  constructor() {
    this.window = new BrowserWindow({
      width: 800,
      minWidth: 800,
      height: 600,
      minHeight: 600,
      webPreferences: {
        preload: getPreloadPath(),
        partition: "persist:spark",
        nodeIntegration: false,
        contextIsolation: true,
      },
      frame: false,
      show: false,
    });

    this.window.once("ready-to-show", () => {
      // Show welcome screen immediately; auth check continues in AppInitializer.
      this.window?.show();
      console.log("Main Window is ready and visible");
    });

    if (isDevMode()) {
      console.log("Development window");
      this.window.webContents.openDevTools();
      this.window.loadURL("http://localhost:5123");
    } else {
      console.log("Production window");
      this.window.loadFile(path.join(app.getAppPath(), "/dist-react/index.html"));
    }

    this.setupListeners();
  }

  private setupListeners() {
    if (!this.window) return;

    this.window.on("maximize", () => {
      ipcWebContentSend("isMainWindowMaximized", this.window!.webContents, true);
    });

    this.window.on("unmaximize", () => {
      ipcWebContentSend("isMainWindowMaximized", this.window!.webContents, false);
    });

    let willClose = false;
    this.window.on("close", (event) => {
      if (willClose) {
        return;
      } else {
        event.preventDefault();
        this.window?.hide();
        if (app.dock) {
          app.dock.hide();
        }
      }
    });

    app.on("will-quit", () => {
      willClose = true;
    });

    this.window.on("show", () => {
      willClose = false;
    });
  }

  public getBrowserWindow(): BrowserWindow {
    if (!this.window) throw new Error("Window not initialized");
    return this.window;
  }

  public minimize() {
    this.window?.minimize();
  }

  public maximize() {
    if (this.window?.isMaximized()) {
      this.window.unmaximize();
    } else {
      this.window?.maximize();
    }
  }

  public close() {
    this.window?.close();
  }

  public setOnboardingWindowMode(
    mode: "IMMERSIVE" | "MAXIMIZED" | "DEFAULT",
  ) {
    if (!this.window) return;

    if (mode === "IMMERSIVE") {
      if (!this.onboardingWindowSnapshot) {
        this.onboardingWindowSnapshot = {
          bounds: this.window.getBounds(),
          wasMaximized: this.window.isMaximized(),
        };
      }

      if (this.window.isMinimized()) {
        this.window.restore();
      }

      this.window.maximize();
      this.window.setFullScreen(true);
      this.window.focus();
      return;
    }

    if (mode === "MAXIMIZED") {
      if (this.window.isMinimized()) {
        this.window.restore();
      }

      this.window.setFullScreen(false);
      this.window.maximize();
      this.window.focus();
      return;
    }

    this.window.setFullScreen(false);

    if (this.onboardingWindowSnapshot?.wasMaximized) {
      this.window.maximize();
    } else {
      if (this.window.isMaximized()) {
        this.window.unmaximize();
      }

      if (this.onboardingWindowSnapshot?.bounds) {
        this.window.setBounds(this.onboardingWindowSnapshot.bounds);
      }
    }

    this.onboardingWindowSnapshot = null;
    this.window.focus();
  }
}
