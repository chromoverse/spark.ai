import { BrowserWindow } from "electron";
import { ipcMainHandle } from "../utils/ipcUtils.js";

export async function registerDeviceHandlers(mainWindow: BrowserWindow) {
  // device usage status handler
  ipcMainHandle("getDeviceUsageStatus", async () => {
    const { getCpuUsage, getRamUsage, getStorageData } = await import("../services/DeviceStatusService.js");
    const cpuUsage = await getCpuUsage();
    const ramUsage = getRamUsage();
    const storageData = getStorageData();
    return { cpuUsage, ramUsage, storageData };
  });

  // continuous polling
  const { poolDeviceStatus } = await import("../services/DeviceStatusService.js");
  poolDeviceStatus(mainWindow);
}
