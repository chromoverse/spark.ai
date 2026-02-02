import fs from "fs";
import os from "os";
import { BrowserWindow } from "electron";
import { IDeviceUsageStatusManager } from "@root/types";
import { ipcWebContentSend } from "../utils/ipcUtils.js";

const POLLING_INTERVAL = 1000;

// Track previous CPU usage for calculation
let previousCpuUsage = process.cpuUsage();
let previousTime = Date.now();

export function poolDeviceStatus(mainWindow: BrowserWindow) {
  setInterval(async () => {
    let cpuUsage = await getCpuUsage();
    let ramUsage = getRamUsage();
    let storageData = getStorageData();

    ipcWebContentSend("getDeviceUsageStatus", mainWindow.webContents, {
      cpuUsage,
      ramUsage,
      storageData,
    } as IDeviceUsageStatusManager);
  }, POLLING_INTERVAL);
}

// Get this app's CPU usage as a percentage
export function getCpuUsage(): Promise<number> {
  return new Promise((resolve) => {
    const currentCpuUsage = process.cpuUsage(previousCpuUsage);
    const currentTime = Date.now();
    const elapsedTime = currentTime - previousTime;

    // Calculate CPU usage percentage
    // cpuUsage is in microseconds, convert to milliseconds and get percentage
    const totalCpuTime = (currentCpuUsage.user + currentCpuUsage.system) / 1000; // Convert to ms
    const cpuPercent = totalCpuTime / elapsedTime / os.cpus().length;

    // Update previous values for next calculation
    previousCpuUsage = process.cpuUsage();
    previousTime = currentTime;

    resolve(Math.min(cpuPercent, 1)); // Cap at 100%
  });
}

// Get this app's RAM usage
export function getRamUsage(): number {
  const memoryUsage = process.memoryUsage();
  const totalSystemMemory = os.totalmem();

  // Use heapUsed + external for app's actual memory
  const appMemoryUsage = memoryUsage.heapUsed + memoryUsage.external;

  return appMemoryUsage / totalSystemMemory;
}

// Get storage data (system-wide)
export function getStorageData(): {
  total: number;
  free: number;
  usage: number;
} {
  const stats = fs.statfsSync(process.platform === "win32" ? "C://" : "/");
  const total = stats.blocks * stats.bsize;
  const free = stats.bfree * stats.bsize;
  return {
    total: Math.floor(total / 1024 / 1024 / 1024), // Convert to GB
    free: Math.floor(free / 1024 / 1024 / 1024), // Convert to GB
    usage: 1 - free / total,
  };
}
