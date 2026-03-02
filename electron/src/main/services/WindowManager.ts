import { MainWindow } from "../windows/MainWindow.js";
import { SecondaryWindow } from "../windows/SecondaryWindow.js";
import { socketService } from "./SocketService.js";

export class WindowManager {
  private mainWindow: MainWindow | null = null;
  private secondaryWindow: SecondaryWindow | null = null;

  public createMainWindow(): MainWindow {
    this.mainWindow = new MainWindow();
    socketService.registerWindow(this.mainWindow.getBrowserWindow());
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

    const secondaryBrowserWindow = this.secondaryWindow.getBrowserWindow();
    if (secondaryBrowserWindow) {
      socketService.registerWindow(secondaryBrowserWindow);
    }
  }

  public getSecondaryWindow(): SecondaryWindow | null {
    return this.secondaryWindow;
  }
}

export const windowManager = new WindowManager();
