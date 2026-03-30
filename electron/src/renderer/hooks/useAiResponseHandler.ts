// src/renderer/hooks/useAiResponseHandler.ts
import { useEffect, useCallback, useRef, useState } from "react";
import { useSocket } from "@/context/socketContextProvider";
import { useSparkTTS } from "@/context/sparkTTSContext";
import type {
  QueryResultPayload,
  TaskRecord,
  TaskOutput,
  TaskExecuteBatchPayload,
  TaskProgressPayload,
} from "@shared/socket.types";

interface UseAiResponseHandlerOptions {
  autoListen?: boolean;
  onPQHSuccess?: (payload: QueryResultPayload) => void;
  onPQHError?: (error: string, payload: QueryResultPayload) => void;
  onTaskBatchReceived?: (tasks: TaskRecord[]) => void;
  onTaskBatchComplete?: (results: TaskOutput[]) => void;
  onTaskBatchError?: (error: string) => void;
}

const GENERIC_TASK_FAILURE_MESSAGE = "I couldn't finish that request.";
const GENERIC_TASK_FAILURE_SPEECH = "माफ करें सर, वह काम पूरा नहीं हो सका।";
const TECHNICAL_ERROR_PATTERNS = [
  /input validation failed/i,
  /parameter ['"]/i,
  /must be [a-z]+/i,
  /got [a-z_]+/i,
  /cannot resolve bindings/i,
  /traceback/i,
  /exception/i,
  /not found in registry/i,
  /not implemented/i,
];

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
  const lastReportedFailureRef = useRef<string | null>(null);

  const isTechnicalErrorMessage = useCallback((message: string): boolean => {
    return TECHNICAL_ERROR_PATTERNS.some((pattern) => pattern.test(message));
  }, []);

  const getFirstFailureMessage = useCallback((payload: TaskProgressPayload) => {
    const failures = payload.summary?.failures;
    if (!Array.isArray(failures) || failures.length === 0) {
      return null;
    }
    const first = failures[0];
    return typeof first?.userMessage === "string" && first.userMessage.trim()
      ? first.userMessage.trim()
      : null;
  }, []);

  const resolveFriendlyFailureMessage = useCallback(
    (preferredMessage?: string | null, fallbackMessage?: string | null) => {
      const preferred = preferredMessage?.trim();
      if (preferred) {
        return preferred;
      }

      const fallback = fallbackMessage?.trim();
      if (fallback && !isTechnicalErrorMessage(fallback)) {
        return fallback;
      }

      return GENERIC_TASK_FAILURE_MESSAGE;
    },
    [isTechnicalErrorMessage],
  );

  const reportTaskFailure = useCallback(
    (message: string) => {
      setError(message);
      setLoading(false);
      setExecutingTasks([]);

      if (lastReportedFailureRef.current !== message) {
        lastReportedFailureRef.current = message;
        onTaskBatchError?.(message);
      }
    },
    [onTaskBatchError],
  );

  // ============================================
  // PQH HANDLER (Primary Query Handler)
  // ============================================
  const handlePQHResponse = useCallback(
    async (payload: QueryResultPayload) => {
      setLoading(true);
      setError(null);
      setCurrentPayload(payload);
      lastReportedFailureRef.current = null;

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
      lastReportedFailureRef.current = null;

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
          const displayMessage = resolveFriendlyFailureMessage(
            null,
            response.message,
          );
          console.error("❌ [SQH] Execution failed:", response.message);
          reportTaskFailure(displayMessage);
          if (displayMessage === GENERIC_TASK_FAILURE_MESSAGE) {
            speak(GENERIC_TASK_FAILURE_SPEECH);
          } else {
            speak(displayMessage);
          }
        }

        setLoading(false);
        setExecutingTasks([]);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to execute tasks";
        console.error("💥 [SQH] Error:", err);
        const displayMessage = resolveFriendlyFailureMessage(null, message);
        reportTaskFailure(displayMessage);
        if (displayMessage === GENERIC_TASK_FAILURE_MESSAGE) {
          speak(GENERIC_TASK_FAILURE_SPEECH);
        } else {
          speak(displayMessage);
        }
      }
    },
    [
      speak,
      onTaskBatchReceived,
      onTaskBatchComplete,
      reportTaskFailure,
      resolveFriendlyFailureMessage,
    ],
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

    // console.log("👂 Setting up AI response listeners");

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

    const handleTaskSummary = (data: TaskProgressPayload) => {
      const failureMessage = getFirstFailureMessage(data);
      if (!failureMessage) {
        return;
      }

      console.log("📡 [SQH] Task summary failure:", data.summary.failures);
      reportTaskFailure(failureMessage);
    };

    // Register listeners
    on("query-result", handleQueryResult);
    on("task:execute", handleTaskExecuteBatchPayload);
    on("task:execute_batch", handleTaskExecuteBatchPayload);
    on("task:progress", handleTaskSummary);
    on("task:summary", handleTaskSummary);

    return () => {
      // console.log("👋 Cleaning up AI response listeners");
      off("query-result", handleQueryResult);
      off("task:execute", handleTaskExecuteBatchPayload);
      off("task:execute_batch", handleTaskExecuteBatchPayload);
      off("task:progress", handleTaskSummary);
      off("task:summary", handleTaskSummary);
    };
  }, [
    socket,
    isConnected,
    autoListen,
    handlePQHResponse,
    handleTaskBatch,
    getFirstFailureMessage,
    on,
    off,
    reportTaskFailure,
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
