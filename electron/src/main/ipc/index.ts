import { MainWindow } from "../windows/MainWindow.js";
import { registerMediaHandlers } from "./mediaHandlers.js";
import { registerWindowHandlers } from "./windowHandlers.js";
import { registerSecondaryWindowHandlers } from "./secondaryWindowHandlers.js";
import { registerBrainHandlers } from "./brainHandlers.js";
import { registerVoiceHandlers } from "./voiceHandlers.js";

export function registerAllHandlers(mainWindow: MainWindow) {
  const browserWindow = mainWindow.getBrowserWindow();
  
  registerMediaHandlers(browserWindow);
  registerWindowHandlers(mainWindow);
  registerSecondaryWindowHandlers();
  registerBrainHandlers();
  registerVoiceHandlers();
}
