import { MainWindow } from "../windows/MainWindow.js";
import { SecondaryWindow } from "../windows/SecondaryWindow.js";

export class WindowManager {
  private mainWindow: MainWindow | null = null;
  private secondaryWindow: SecondaryWindow | null = null;

  public createMainWindow(): MainWindow {
    this.mainWindow = new MainWindow();
    return this.mainWindow;
  }

  public getMainWindow(): MainWindow {
    if (!this.mainWindow) throw new Error("Main window not initialized");
    return this.mainWindow;
  }

  public openSecondaryWindow() {
    if (!this.secondaryWindow) {
      this.secondaryWindow = new SecondaryWindow();
    } else {
      this.secondaryWindow.show();
    }
  }

  public getSecondaryWindow(): SecondaryWindow | null {
    return this.secondaryWindow;
  }
}

export const windowManager = new WindowManager();
