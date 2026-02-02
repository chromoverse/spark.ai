// src/renderer/hooks/useAiResponseHandler.ts
import { useEffect, useCallback, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";
import { useSparkTTS } from "@/context/sparkTTSContext";
import type {
  QueryResultPayload,
  TaskRecord,
  TaskOutput,
  TaskExecuteBatchPayload,
} from "@shared/socket.types";

interface UseAiResponseHandlerOptions {
  autoListen?: boolean;
  onPQHSuccess?: (payload: QueryResultPayload) => void;
  onPQHError?: (error: string, payload: QueryResultPayload) => void;
  onTaskBatchReceived?: (tasks: TaskRecord[]) => void;
  onTaskBatchComplete?: (results: TaskOutput[]) => void;
  onTaskBatchError?: (error: string) => void;
}

export function useAiResponseHandler(
  options: UseAiResponseHandlerOptions = {},
) {
  const {
    autoListen = true,
    onPQHSuccess,
    onPQHError,
    onTaskBatchReceived,
    onTaskBatchComplete,
    onTaskBatchError,
  } = options;

  const { socket, isConnected, on, off } = useSocket();
  const { speak, stop: stopTTS, isSpeaking } = useSparkTTS();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPayload, setCurrentPayload] =
    useState<QueryResultPayload | null>(null);
  const [executingTasks, setExecutingTasks] = useState<TaskRecord[]>([]);

  // ============================================
  // PQH HANDLER (Primary Query Handler)
  // ============================================
  const handlePQHResponse = useCallback(
    async (payload: QueryResultPayload) => {
      setLoading(true);
      setError(null);
      setCurrentPayload(payload);

      try {
        console.log("🤖 [PQH] Processing:", payload);

        // STEP 1: Speak the answer
        if (payload.cognitiveState.answer) {
          console.log("🎤 Speaking:", payload.cognitiveState.answer);
          speak(payload.cognitiveState.answer);
          await waitForSpeechComplete();
        }

        // STEP 2: Check if there are tools to execute
        if (!payload.requestedTool || payload.requestedTool.length === 0) {
          console.log("ℹ️ No tools requested");
          setLoading(false);
          onPQHSuccess?.(payload);
          return;
        }

        console.log("✅ [PQH] Response handled");
        onPQHSuccess?.(payload);
        setLoading(false);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to process PQH response";
        console.error("💥 [PQH] Error:", err);
        setError(message);
        setLoading(false);
        speak("माफ करें सर, कुछ गड़बड़ हो गई।");
        onPQHError?.(message, payload);
      }
    },
    [speak, onPQHSuccess, onPQHError],
  );

  // ============================================
  // SQH HANDLER (Secondary Query Handler - Task Orchestration)
  // ============================================
  const handleTaskBatch = useCallback(
    async (payload: TaskExecuteBatchPayload) => {
      setLoading(true);
      setError(null);
      setExecutingTasks(payload.tasks);

      try {
        console.log(`🎯 [SQH] Received ${payload.tasks.length} tasks`);
        console.log("Tasks:", payload.tasks);

        onTaskBatchReceived?.(payload.tasks);

        // Speak lifecycle messages for first task
        const firstTask = payload.tasks[0];
        if (firstTask?.task.lifecycleMessages?.onStart) {
          speak(firstTask.task.lifecycleMessages.onStart);
          await waitForSpeechComplete();
        }

        // Execute tasks via IPC
        console.log("⚙️ [SQH] Executing tasks...", payload.tasks);
        const response = await window.electronApi.executeTasks(payload.tasks);

        console.log("📥 [SQH] Execution response:", response);

        // Handle results
        if (response.status === "ok") {
          console.log(`✅ [SQH] All tasks completed`);

          // Speak success message from last successful task
          const successfulTasks = response.results.filter(
            (r: TaskOutput) => r.success,
          );
          if (successfulTasks.length > 0) {
            const lastSuccess = successfulTasks[successfulTasks.length - 1];
            const taskRecord = payload.tasks.find(
              (t) => t.task.taskId === lastSuccess.taskId,
            );
            if (taskRecord?.task.lifecycleMessages?.onSuccess) {
              speak(taskRecord.task.lifecycleMessages.onSuccess);
            }
          }

          onTaskBatchComplete?.(response.results);
        } else {
          console.error("❌ [SQH] Execution failed:", response.message);
          setError(response.message);
          speak("माफ करें सर, कुछ गड़बड़ हो गई।");
          onTaskBatchError?.(response.message);
        }

        setLoading(false);
        setExecutingTasks([]);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to execute tasks";
        console.error("💥 [SQH] Error:", err);
        setError(message);
        setLoading(false);
        setExecutingTasks([]);
        speak("माफ करें सर, कुछ गड़बड़ हो गई।");
        onTaskBatchError?.(message);
      }
    },
    [speak, onTaskBatchReceived, onTaskBatchComplete, onTaskBatchError],
  );

  // ============================================
  // HELPERS
  // ============================================
  const waitForSpeechComplete = useCallback((): Promise<void> => {
    return new Promise((resolve) => {
      if (!isSpeaking) {
        resolve();
        return;
      }

      const checkInterval = setInterval(() => {
        if (!isSpeaking) {
          clearInterval(checkInterval);
          resolve();
        }
      }, 100);

      setTimeout(() => {
        clearInterval(checkInterval);
        resolve();
      }, 30000);
    });
  }, [isSpeaking]);

  // ============================================
  // SOCKET LISTENERS
  // ============================================
  useEffect(() => {
    if (!autoListen || !socket || !isConnected) return;

    console.log("👂 Setting up AI response listeners");

    // PQH listener
    const handleQueryResult = (data: QueryResultPayload) => {
      console.log("📡 [PQH] query-result:", data);
      handlePQHResponse(data);
    };

    // Unified task handler - server always sends { user_id, tasks: [...] }
    const handleTaskExecuteBatchPayload = (data: TaskExecuteBatchPayload) => {
      console.log("📡 [SQH] Task payload received:", data);
      handleTaskBatch(data);
    };

    // Register listeners
    on("query-result", handleQueryResult);
    on("task:execute", handleTaskExecuteBatchPayload);
    on("task:execute_batch", handleTaskExecuteBatchPayload);

    return () => {
      console.log("👋 Cleaning up AI response listeners");
      off("query-result", handleQueryResult);
      off("task:execute", handleTaskExecuteBatchPayload);
      off("task:execute_batch", handleTaskExecuteBatchPayload);
    };
  }, [
    socket,
    isConnected,
    autoListen,
    handlePQHResponse,
    handleTaskBatch,
    on,
    off,
  ]);

  // ============================================
  // RETURN API
  // ============================================
  return {
    // State
    loading,
    error,
    currentPayload,
    executingTasks,
    isSpeaking,

    // Actions
    stopSpeaking: stopTTS,
  };
}

// ============================================
// USAGE EXAMPLES
// ============================================

/*
// Example 1: Top-level auto-listener (recommended)
function App() {
  useAiResponseHandler({
    autoListen: true,
    onPQHSuccess: (payload) => {
      console.log("PQH completed:", payload);
    },
    onTaskBatchComplete: (results) => {
      console.log("Tasks completed:", results);
      // Update UI, show notifications, etc.
    },
    onTaskBatchError: (error) => {
      console.error("Tasks failed:", error);
      // Show error toast
    }
  });

  return <YourAppContent />;
}

// Example 2: Show task execution status
function TaskStatusDisplay() {
  const { executingTasks, loading } = useAiResponseHandler();

  if (!loading || executingTasks.length === 0) return null;

  return (
    <div>
      <h3>Executing Tasks:</h3>
      {executingTasks.map(t => (
        <div key={t.task.taskId}>
          {t.task.tool}: {t.status}
        </div>
      ))}
    </div>
  );
}

// Example 3: Manual control
function ControlPanel() {
  const { loading, error, stopSpeaking } = useAiResponseHandler();

  return (
    <div>
      {loading && <Spinner />}
      {error && <ErrorBanner message={error} />}
      <button onClick={stopSpeaking}>Stop Speaking</button>
    </div>
  );
}
*/
