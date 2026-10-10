import { BrowserWindow, app, screen } from "electron";
import path from "node:path";
import { getPreloadPath } from "../utils/pathResolver.js";
import { isDevMode } from "../utils/isDevMode.js";

// The voice overlay: a notch hanging from the top edge of the screen. The window never resizes or
// moves (resizing it per hover made the old pill jump and clip): it is fixed at the largest size
// the notch can grow to, transparent and click-through, and the notch morphs inside it in CSS.
// The renderer turns clicks on while the pointer is over the notch itself (overlayInteractive).
const WIDTH = 640;
const HEIGHT = 480;

export class SecondaryWindow {
  private window: BrowserWindow | null = null;

  constructor() {
    this.window = new BrowserWindow({
      ...this.bounds(),
      frame: false,
      transparent: true,
      backgroundColor: "#00000000",
      resizable: false,
      movable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      hasShadow: false, // a native shadow on a transparent window draws a box; the notch has its own
      show: false,
      webPreferences: {
        preload: getPreloadPath(),
        partition: "persist:spark",
        nodeIntegration: false,
        contextIsolation: true,
        backgroundThrottling: false, // the ear and the voice live here
      },
    });

    this.window.setAlwaysOnTop(true, "screen-saver");
    this.window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    this.setInteractive(false);

    this.window.on("minimize", () => this.window?.restore());
    this.window.on("hide", () => {
      // Use showInactive to avoid stealing focus from main window
      this.window?.showInactive();
      this.window?.setAlwaysOnTop(true, "screen-saver");
    });
    this.window.once("ready-to-show", () => this.window?.showInactive());

    const place = (): void => this.window?.setBounds(this.bounds());
    screen.on("display-metrics-changed", place);
    screen.on("display-added", place);
    screen.on("display-removed", place);
    this.window.on("closed", () => {
      screen.off("display-metrics-changed", place);
      screen.off("display-added", place);
      screen.off("display-removed", place);
      this.window = null;
    });

    if (isDevMode()) {
      this.window.loadURL("http://localhost:5123/#/ai-panel");
    } else {
      this.window.loadFile(path.join(app.getAppPath(), "/dist-react/index.html"), { hash: "ai-panel" });
    }
  }

  /** Top-center of the primary display, flush with its top edge. */
  private bounds(): Electron.Rectangle {
    const area = screen.getPrimaryDisplay().workArea;
    return { x: Math.round(area.x + (area.width - WIDTH) / 2), y: area.y, width: WIDTH, height: HEIGHT };
  }

  /** Clicks reach the notch only while the pointer is on it; elsewhere they fall through. */
  public setInteractive(on: boolean): void {
    if (on) this.window?.setIgnoreMouseEvents(false);
    else this.window?.setIgnoreMouseEvents(true, { forward: true });
  }

  public show() {
    this.window?.showInactive();
  }

  public getBrowserWindow() {
    return this.window;
  }
}
