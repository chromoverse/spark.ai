import path from "path";
import { app } from "electron";
import { isDevMode } from "./isDevMode.js"

export function getPreloadPath() {
  return path.join(
    app.getAppPath(),
    isDevMode() ? "." : "..",
    "dist-electron",
    "main",
    "preload.cjs"
  );
}

export function getUIPath(): string {
  if (isDevMode()) {
    return path.join(app.getAppPath(), "dist-react", "index.html");
  } else {
    // In production, dist-react is in extraResources (unpacked)
    // process.resourcesPath is set by electron-builder
    const resourcesPath = process.resourcesPath || path.join(app.getAppPath(), "..", "resources");
    return path.join(resourcesPath, "dist-react", "index.html");
  }
}

export function getAssetPath() {
  return path.join(app.getAppPath(), isDevMode() ? "." : "..", "src", "assets");
}
