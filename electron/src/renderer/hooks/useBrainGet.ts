import { useCallback, useEffect, useState } from "react";

/** GET a brain route through main (tokens never reach the renderer). `reload` re-fetches;
 * a null path waits. */
export function useBrainGet<T>(path: string | null): {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
} {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: path !== null });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (path === null) return;
    let live = true;
    void window.electronApi.brain.request("GET", path).then((r) => {
      if (!live) return;
      setState(r.ok ? { data: r.data as T, error: null, loading: false } : { data: null, error: r.error.message, loading: false });
    });
    return () => {
      live = false;
    };
  }, [path, tick]);

  return { ...state, reload };
}
