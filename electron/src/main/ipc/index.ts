import { MainWindow } from "../windows/MainWindow.js";
import { registerMediaHandlers } from "./mediaHandlers.js";
import { registerDeviceHandlers } from "./deviceHandlers.js";
import { registerWindowHandlers } from "./windowHandlers.js";
import { registerTaskHandlers } from "./taskHandlers.js";
import { registerSecondaryWindowHandlers } from "./secondaryWindowHandlers.js";
import { registerSocketHandlers } from "./socketHandlers.js";
import { registerBrainHandlers } from "./brainHandlers.js";

export function registerAllHandlers(mainWindow: MainWindow) {
  const browserWindow = mainWindow.getBrowserWindow();
  
  registerMediaHandlers(browserWindow);
  registerDeviceHandlers(browserWindow);
  registerWindowHandlers(mainWindow);
  registerTaskHandlers();
  registerSecondaryWindowHandlers();
  registerSocketHandlers();
  registerBrainHandlers();
}
