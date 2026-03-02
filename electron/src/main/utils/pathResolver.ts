import path from "path";
import fs from "node:fs";
import { app } from "electron";
import { isDevMode } from "./isDevMode.js"

function firstExistingPath(candidates: string[]): string {
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
}

export function getPreloadPath() {
  const appPath = app.getAppPath();
  const cwd = process.cwd();

  return firstExistingPath([
    path.join(appPath, "dist-electron", "main", "preload.cjs"),
    path.join(appPath, "electron", "dist-electron", "main", "preload.cjs"),
    path.join(cwd, "dist-electron", "main", "preload.cjs"),
    path.join(cwd, "electron", "dist-electron", "main", "preload.cjs"),
  ]);
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
  const appPath = app.getAppPath();
  const cwd = process.cwd();

  return firstExistingPath([
    path.join(appPath, "src", "assets"),
    path.join(appPath, "electron", "src", "assets"),
    path.join(cwd, "src", "assets"),
    path.join(cwd, "electron", "src", "assets"),
  ]);
}
