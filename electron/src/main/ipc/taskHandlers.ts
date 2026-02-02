// src/main/handlers/taskHandlers.ts
import { ipcMainHandle } from "../utils/ipcUtils.js";
import {
  executeTaskBatch,
  isActionExecutorRunning,
} from "../services/ActionExecutorService.js";
import type { TaskRecord } from "@shared/socket.types.js";

/**
 * Register IPC handlers for task execution
 */
export function registerTaskHandlers() {
  /**
   * Execute a batch of tasks
   *
   * Handler: "executeTasks"
   * Input: TaskRecord[]
   * Output: { status, results, message }
   */
  ipcMainHandle("executeTasks", async (_event, tasks: TaskRecord[]) => {
    console.log(`🔵 IPC: executeTasks called with ${tasks.length} tasks`);

    try {
      // Validate executor is running
      if (!isActionExecutorRunning()) {
        console.error("❌ Action Executor is not running!");
        return {
          status: "error" as const,
          results: [],
          message: "Action Executor process is not running",
        };
      }

      // Validate input
      if (!Array.isArray(tasks) || tasks.length === 0) {
        console.error("❌ Invalid tasks input");
        return {
          status: "error" as const,
          results: [],
          message: "Invalid tasks input - expected non-empty array",
        };
      }

      console.log(`🔵 Sending ${tasks.length} tasks to executor...`);

      // Execute tasks
      const result = await executeTaskBatch(tasks);

      console.log(`🔵 Executor response:`, result);

      return result;
    } catch (err: any) {
      console.error("❌ Error in executeTasks:", err);
      return {
        status: "error" as const,
        results: [],
        message: err.message || "Unknown error executing tasks",
      };
    }
  });

  console.log("✅ Task IPC handlers registered");
}
