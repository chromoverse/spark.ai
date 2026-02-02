import { BrowserWindow, app } from "electron";
import * as path from "node:path";
import { getPreloadPath, getUIPath } from "../utils/pathResolver.js";
import { isDevMode } from "../utils/isDevMode.js";
import { ipcWebContentSend } from "../utils/ipcUtils.js";

export class MainWindow {
  private window: BrowserWindow | null = null;

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
      this.window?.show();
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
}
