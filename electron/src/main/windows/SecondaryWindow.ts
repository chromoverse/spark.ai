import { BrowserWindow, app, screen } from "electron";
import path from "node:path";
import { getPreloadPath } from "../utils/pathResolver.js";
import { isDevMode } from "../utils/isDevMode.js";

export class SecondaryWindow {
  private window: BrowserWindow | null = null;

  constructor() {
    const display = screen.getPrimaryDisplay().workAreaSize;

    this.window = new BrowserWindow({
      width: 220, // 🔥 collapsed size (dynamic resize will expand)
      height: 70,
      x: Math.round((display.width - 220) / 2), // 🎯 centered horizontally
      y: 0, // 📌 attached to top edge (snackbar style)
      frame: false, // ❌ remove OS chrome
      transparent: true, // 🌫 glass effect
      resizable: false,
      minimizable: false,
      maximizable: false,
      // closable: false,
      alwaysOnTop: true, // 🧲 stay above apps
      skipTaskbar: true,
      hasShadow: true,
      show: false,
      webPreferences: {
        preload: getPreloadPath(),
        partition: "persist:spark",
        nodeIntegration: false,
        contextIsolation: true,
      },
    });

    // 🔒 Strongest overlay level
    this.window.setAlwaysOnTop(true, "screen-saver");
    this.window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

    // 🚫 Refuse minimize
    this.window.on("minimize", () => {
      this.window?.restore();
    });

    this.window.on("hide", () => {
      this.window?.show();
    });

    this.window.once("ready-to-show", () => {
      this.window?.show();
    });

    if (isDevMode()) {
      this.window.loadURL("http://localhost:5123/#/ai-panel");
    } else {
      this.window.loadFile(
        path.join(app.getAppPath(), "/dist-react/index.html"),
        { hash: "ai-panel" }
      );
    }

    // 🔒 Limit dragging to upper area (no bottom) of CURRENT display
    this.window.on("will-move", (e, newBounds) => {
      // Find the display the window is engaging with
      const nearestDisplay = screen.getDisplayMatching(newBounds);
      const workArea = nearestDisplay.workArea;

      const minY = workArea.y;
      const maxY = workArea.y + Math.floor(workArea.height / 2);
      
      // Prevent dragging below the middle of the screen
      if (newBounds.y > maxY) {
        newBounds.y = maxY;
      }
      
      // Prevent dragging off-screen top (respect display y)
      if (newBounds.y < minY) {
        newBounds.y = minY;
      }
    });

    this.window.on("closed", () => {
      this.window = null;
    });
  }

  public show() {
    this.window?.show();
    this.window?.focus();
  }

  public getBrowserWindow() {
    return this.window;
  }

  /**
   * Smoothly resize the window with animation
   * Uses setBounds with animate flag for buttery smooth transitions
   */
  public setSize(width: number, height: number) {
    if (!this.window) return;

    const currentBounds = this.window.getBounds();
    
    // Calculate new X to expand quickly from center
    // newX = currentX - (changeInWidth / 2)
    const newX = Math.round(currentBounds.x - (width - currentBounds.width) / 2);

    // Use setBounds with animate flag for smooth transitions
    this.window.setBounds(
      {
        x: newX,
        y: currentBounds.y, // Keep current Y position
        width: Math.round(width),
        height: Math.round(height),
      },
      false, // ⚡ DISABLE ANIMATION - Let CSS handle it
    );
  }

  public getBounds(): Electron.Rectangle {
    if (!this.window) throw new Error("Window not initialized");
    return this.window.getBounds();
  }

  /**
   * Set bounds with optional animation
   */
  public setBounds(
    bounds: Partial<Electron.Rectangle>,
    animate: boolean = false,
  ) {
    if (!this.window) return;

    const currentBounds = this.window.getBounds();
    const newBounds = {
      x: bounds.x ?? currentBounds.x,
      y: bounds.y ?? currentBounds.y, // Respect current Y or passed Y
      width: bounds.width ?? currentBounds.width,
      height: bounds.height ?? currentBounds.height,
    };

    this.window.setBounds(newBounds, animate);
  }
}
