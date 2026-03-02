import { app } from "electron";

export function isDevMode(): boolean {
  return !app.isPackaged;
}
