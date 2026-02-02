// src/main/services/ActionExecutorService.ts
import { ChildProcess, spawn } from "node:child_process";
import { app } from "electron";
import type { TaskRecord } from "@shared/socket.types.js";

let executorProcess: ChildProcess | null = null;

/**
 * Start the Python action executor service
 */
export function startActionExecutor() {
  const pythonCommand = process.platform === "win32" ? "python" : "python3";
  // Use app.getAppPath() to get the correct project root in both dev and prod
  const projectRoot = app.getAppPath();

  console.log("=== STARTING ACTION EXECUTOR ===");
  console.log("Running as module: action_executor.electron_bridge");
  console.log("Python command:", pythonCommand);
  console.log("Working directory:", projectRoot);

  // Run as module (-m) so Python relative imports work correctly
  executorProcess = spawn(pythonCommand, ["-m", "action_executor.electron_bridge"], {
    cwd: projectRoot,
    stdio: ["pipe", "pipe", "pipe"],
  });

  console.log("✅ Action Executor spawned with PID:", executorProcess.pid);

  // Handle stdout (normal logs)
  if (executorProcess.stdout) {
    executorProcess.stdout.on("data", (data) => {
      const message = data.toString();
      console.log(`[Executor] ${message.trim()}`);
    });
  }

  // Handle stderr (logs and lifecycle messages)
  if (executorProcess.stderr) {
    executorProcess.stderr.on("data", (data) => {
      const message = data.toString();

      // Parse lifecycle messages (sent by Python for TTS)
      if (message.includes("LIFECYCLE:")) {
        const match = message.match(/LIFECYCLE:(.+)/);
        if (match) {
          const lifecycleMsg = match[1].trim();
          console.log(`💬 Lifecycle: ${lifecycleMsg}`);
          // TODO: Emit to client for TTS
          // socket.emit("tts-lifecycle", { message: lifecycleMsg });
        }
      }
      // Parse progress updates
      else if (message.includes("PROGRESS:")) {
        const match = message.match(/PROGRESS:(\d+)%/);
        if (match) {
          const progress = parseInt(match[1]);
          console.log(`⏳ Progress: ${progress}%`);
          // TODO: Emit progress to client
        }
      }
      // Regular logs
      else {
        console.log(`[Executor] ${message.trim()}`);
      }
    });
  }

  executorProcess.on("error", (error) => {
    console.error(`❌ Failed to start executor process:`, error);
  });

  executorProcess.on("exit", (code) => {
    console.log(`Action Executor exited with code ${code}`);
    executorProcess = null;
  });
}

/**
 * Stop the action executor service
 */
export function killActionExecutor() {
  if (executorProcess) {
    executorProcess.kill();
    executorProcess = null;
    console.log("🛑 Action Executor stopped");
  }
}

/**
 * Check if action executor is running
 */
export function isActionExecutorRunning(): boolean {
  return executorProcess !== null;
}

/**
 * Execute a batch of tasks
 *
 * @param tasks - Array of TaskRecord objects to execute
 * @returns Promise with execution results
 */
export async function executeTaskBatch(tasks: TaskRecord[]): Promise<any> {
  console.log(`📤 executeTaskBatch called with ${tasks.length} tasks`);

  if (!executorProcess) {
    throw new Error("Action Executor process is not running");
  }

  return new Promise((resolve, reject) => {
    if (!executorProcess?.stdout || !executorProcess?.stdin) {
      return reject(new Error("Executor process streams are not available"));
    }

    // ============================================
    // TIMEOUT CALCULATION
    // ============================================
    // Base timeout per task
    const timeoutPerTask = 30000; // 30s per task
    const totalTimeout = Math.min(
      tasks.length * timeoutPerTask,
      300000, // Max 5 minutes
    );

    const timeout = setTimeout(() => {
      executorProcess?.stdout?.removeListener("data", dataHandler);
      console.error(`⏱️ Task batch timed out after ${totalTimeout / 1000}s`);
      reject(
        new Error(`Task execution timed out after ${totalTimeout / 1000}s`),
      );
    }, totalTimeout);

    let buffer = "";

    const dataHandler = (raw: Buffer) => {
      const chunk = raw.toString();
      buffer += chunk;

      // Try to parse accumulated buffer
      try {
        const parsed = JSON.parse(buffer);
        clearTimeout(timeout);
        executorProcess?.stdout?.removeListener("data", dataHandler);
        console.log("✅ Parsed executor response:", parsed);
        resolve(parsed);
        buffer = "";
      } catch (e) {
        // Incomplete JSON, continue waiting
      }
    };

    // Clean up any existing listeners and add the new one
    executorProcess.stdout.removeAllListeners("data");
    executorProcess.stdout.on("data", dataHandler);

    try {
      // Send task batch to Python
      const payload = {
        tasks: tasks,
      };

      const jsonData = JSON.stringify(payload) + "\n";
      executorProcess.stdin.write(jsonData);

      console.log(`📨 Sent ${tasks.length} tasks to executor`);
    } catch (err) {
      clearTimeout(timeout);
      executorProcess?.stdout?.removeListener("data", dataHandler);
      reject(new Error(`Failed to write to executor: ${err}`));
    }
  });
}
