import { BrowserWindow, Menu, Tray, app, nativeImage, MenuItemConstructorOptions } from "electron";
import * as path from "node:path";
import { getAssetPath } from "../utils/pathResolver.js";
import { windowManager } from "../services/WindowManager.js";
import { ipcWebContentSend } from "../utils/ipcUtils.js";
import type { IMediaDevice } from "@root/types";

class TrayManager {
  private tray: Tray | null = null;
  private mainWindow: BrowserWindow | null = null;
  
  // Media States
  private isMicOn: boolean = false;
  private isCameraOn: boolean = false;

  // Device Lists & Selection
  private audioInputs: IMediaDevice[] = [];
  private videoInputs: IMediaDevice[] = [];
  private selectedInputDeviceId: string | null = null;
  private selectedCameraDeviceId: string | null = null;

  public init(mainWindow: BrowserWindow) {
    this.mainWindow = mainWindow;
    const iconPath = path.join(getAssetPath(), "icon.png");
    this.tray = new Tray(nativeImage.createFromPath(iconPath));
    this.tray.setToolTip("Spark AI Assistant");

    this.tray.on("double-click", () => {
      this.toggleMainWindow();
    });

    this.rebuildMenu();
  }

  public updateMediaState(state: { 
    micOn?: boolean; 
    cameraOn?: boolean;
    audioInputs?: IMediaDevice[];
    videoInputs?: IMediaDevice[];
    selectedInputDeviceId?: string | null;
    selectedCameraDeviceId?: string | null;
  }) {
    if (state.micOn !== undefined) this.isMicOn = state.micOn;
    if (state.cameraOn !== undefined) this.isCameraOn = state.cameraOn;
    
    if (state.audioInputs !== undefined) this.audioInputs = state.audioInputs;
    if (state.videoInputs !== undefined) this.videoInputs = state.videoInputs;
    
    if (state.selectedInputDeviceId !== undefined) this.selectedInputDeviceId = state.selectedInputDeviceId;
    if (state.selectedCameraDeviceId !== undefined) this.selectedCameraDeviceId = state.selectedCameraDeviceId;

    this.rebuildMenu();
  }

  public rebuildMenu() {
    if (!this.tray) return;

    const mainWin = this.mainWindow;
    const secondaryWin = windowManager.getSecondaryWindow()?.getBrowserWindow();

    const isMainVisible = mainWin ? mainWin.isVisible() : false;
    const isAiPanelVisible = secondaryWin ? secondaryWin.isVisible() : false;

    // Build Microphone Submenu
    const micSubmenu: MenuItemConstructorOptions[] = this.audioInputs.map((device) => ({
      label: device.label || "Unknown Microphone",
      type: "radio",
      checked: this.selectedInputDeviceId === device.deviceId,
      click: () => this.sendDeviceSelectToRenderer("MIC", device.deviceId),
    }));

    if (micSubmenu.length === 0) {
      micSubmenu.push({ label: "No Microphones Found", enabled: false });
    }

    // Build Camera Submenu
    const cameraSubmenu: MenuItemConstructorOptions[] = this.videoInputs.map((device) => ({
      label: device.label || "Unknown Camera",
      type: "radio",
      checked: this.selectedCameraDeviceId === device.deviceId,
      click: () => this.sendDeviceSelectToRenderer("CAMERA", device.deviceId),
    }));

    if (cameraSubmenu.length === 0) {
      cameraSubmenu.push({ label: "No Cameras Found", enabled: false });
    }

    const contextMenu = Menu.buildFromTemplate([
      {
        label: this.isMicOn ? "🎤 Mute Microphone" : "🎤 Unmute Microphone",
        click: () => this.sendMediaToggleToRenderer("MIC"),
      },
      {
        label: "🎙️ Microphones",
        submenu: micSubmenu,
      },
      { type: "separator" },
      {
        label: this.isCameraOn ? "📷 Turn Off Camera" : "📷 Turn On Camera",
        click: () => this.sendMediaToggleToRenderer("CAMERA"),
      },
      {
        label: "📸 Cameras",
        submenu: cameraSubmenu,
      },
      { type: "separator" },
      {
        label: isMainVisible ? "Hide Main App" : "Show Main App",
        click: () => this.toggleMainWindow(),
      },
      {
        label: isAiPanelVisible ? "Hide AI Panel" : "Show AI Panel",
        click: () => this.toggleAiPanel(),
      },
      { type: "separator" },
      {
        label: "Quit Spark",
        click: () => {
          // Bypass app.on('will-quit') default prevention to forcibly kill the process
          app.exit(0);
        },
      },
    ]);

    this.tray.setContextMenu(contextMenu);
  }

  private sendMediaToggleToRenderer(type: "MIC" | "CAMERA") {
    const targetWebContents = this.getActiveWebContents();
    if (targetWebContents) {
      ipcWebContentSend("onTrayMediaToggle", targetWebContents, { type });
    }
  }

  private sendDeviceSelectToRenderer(type: "MIC" | "CAMERA", deviceId: string) {
    const targetWebContents = this.getActiveWebContents();
    if (targetWebContents) {
      ipcWebContentSend("onTrayDeviceSelect", targetWebContents, { type, deviceId });
    }
  }

  private getActiveWebContents() {
    // Prefer AI Panel if it's open
    const secondaryWin = windowManager.getSecondaryWindow()?.getBrowserWindow();
    if (secondaryWin && secondaryWin.isVisible()) {
      return secondaryWin.webContents;
    }
    return this.mainWindow?.webContents;
  }

  private toggleMainWindow() {
    if (!this.mainWindow) return;
    if (this.mainWindow.isVisible()) {
      this.mainWindow.hide();
    } else {
      this.mainWindow.show();
    }
    this.rebuildMenu(); // Update menu text
  }

  private toggleAiPanel() {
    const secondaryWin = windowManager.getSecondaryWindow();
    if (!secondaryWin) {
      windowManager.openSecondaryWindow(); // Creates & shows it
    } else {
      const browserWin = secondaryWin.getBrowserWindow();
      if (browserWin?.isVisible()) {
        browserWin.hide();
      } else {
        secondaryWin.show();
      }
    }
    this.rebuildMenu(); // Update menu text
  }
}

export const trayManager = new TrayManager();

