import { ipcMainHandle } from "../utils/ipcUtils.js";
import { windowManager } from "../services/WindowManager.js";

export function registerSecondaryWindowHandlers() {
  ipcMainHandle("openSecondaryWindow", () => {
    windowManager.openSecondaryWindow();
  });

  ipcMainHandle("resizeSecondaryWindow", (_event, raw) => {
    const { width, height } = (raw ?? {}) as { width?: unknown; height?: unknown };
    const ok = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0 && n <= 10_000;
    if (!ok(width) || !ok(height)) throw new Error("resizeSecondaryWindow expects positive width/height");
    const secondaryWindow = windowManager.getSecondaryWindow();
    if (secondaryWindow) {
      const bounds = secondaryWindow.getBounds();
      const newX = Math.round(bounds.x + (bounds.width - width) / 2);
      secondaryWindow.setBounds({ x: newX, y: bounds.y, width, height });
    }
  });
}
