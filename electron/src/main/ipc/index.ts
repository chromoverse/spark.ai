import { MainWindow } from "../windows/MainWindow.js";
import { registerMediaHandlers } from "./mediaHandlers.js";
import { registerTokenHandlers } from "./tokenHandlers.js";
import { registerDeviceHandlers } from "./deviceHandlers.js";
import { registerWindowHandlers } from "./windowHandlers.js";
import { registerTaskHandlers } from "./taskHandlers.js";
import { registerSecondaryWindowHandlers } from "./secondaryWindowHandlers.js";

export function registerAllHandlers(mainWindow: MainWindow) {
  const browserWindow = mainWindow.getBrowserWindow();
  
  registerMediaHandlers(browserWindow);
  registerTokenHandlers();
  registerDeviceHandlers(browserWindow);
  registerWindowHandlers(mainWindow);
  registerTaskHandlers();
  registerSecondaryWindowHandlers();
}
