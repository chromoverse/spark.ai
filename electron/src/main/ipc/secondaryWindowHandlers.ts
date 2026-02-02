import { ipcMainHandle } from "../utils/ipcUtils.js";
import { windowManager } from "../services/WindowManager.js";

export function registerSecondaryWindowHandlers() {
  ipcMainHandle("openSecondaryWindow", () => {
    windowManager.openSecondaryWindow();
  });

  ipcMainHandle("resizeSecondaryWindow", (_, { width, height }: { width: number; height: number }) => {
    const secondaryWindow = windowManager.getSecondaryWindow();
    if (secondaryWindow) {
      const bounds = secondaryWindow.getBounds();
      const newX = Math.round(bounds.x + (bounds.width - width) / 2);
      secondaryWindow.setBounds({ x: newX, y: bounds.y, width, height });
    }
  });
}
