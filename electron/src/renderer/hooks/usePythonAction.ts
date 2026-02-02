// src/renderer/hooks/usePythonAction.ts
import { useState } from 'react';
import type{ IAiResponsePayload, IPythonActionResponse } from '../../../types';

export function usePythonAction() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const execute = async (payload: IAiResponsePayload): Promise<IPythonActionResponse> => {
    setLoading(true);
    setError(null);

    try {
      const response = await window.electronApi.runPythonAction(payload);
      
      if (response.status === "error") {
        setError(response.message || "Unknown error");
      }
      
      return response;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to execute Python action";
      setError(message);
      return { status: "error", message };
    } finally {
      setLoading(false);
    }
  };

  return { execute, loading, error };
}

// import { usePythonAction } from './hooks/usePythonAction';

// function MyComponent() {
//   const { execute, loading, error } = usePythonAction();

//   const handleOpenApp = async () => {
//     const response = await execute({
//       action: "OPEN_APP",
//       actionDetails: { appName: "notepad" }
//     });

//     if (response.status === "ok") {
//       console.log("Success:", response.result);
//     }
//   };

//   return (
//     <button onClick={handleOpenApp} disabled={loading}>
//       {loading ? "Loading..." : "Open Notepad"}
//     </button>
//   );
// }