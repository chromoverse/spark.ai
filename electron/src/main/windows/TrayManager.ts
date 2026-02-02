import { BrowserWindow, Menu, Tray, app, nativeImage } from "electron";
import * as path from "node:path";
import { getAssetPath } from "../utils/pathResolver.js";
import { windowManager } from "../services/WindowManager.js";

export function createTray(mainWindow: BrowserWindow) {
  const iconPath = path.join(getAssetPath(), "icon.png");
  const tray = new Tray(nativeImage.createFromPath(iconPath));

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Mute Microphone",
      click: () => {
        mainWindow.show();
      },
    },
    {
      label: "Off Camera",
      click: () => {
        mainWindow.show();
      },
    },
    {
      label: "Open",
      click: () => {
        mainWindow.show();
      },
    },
    {
      type: "separator",
    },
    {
      label: "Settings",
      click: () => {
        windowManager.openSecondaryWindow();
      },
    },
    {
      label: "Quit",
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setToolTip("AI Assistant");
  tray.setContextMenu(contextMenu);

  tray.on("double-click", () => {
    mainWindow.show();
  });

  return tray;
}
