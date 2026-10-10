import { useEffect } from "react";
import type { IBrainSettings, IBrainStatus } from "@root/types";
import { useAppDispatch } from "@/store/hooks";
import { mergeBrainSettings, setBrainStatus } from "@/store/features/brain/brainSlice";
import { brainEvent, jobsLoaded } from "@/store/features/spark/sparkSlice";

/** Mirrors the main process's brain socket into Redux: connection status and pushed events
 * (each window has its own store, so every window folds every event). */
export function useBrainBridge(): void {
  const dispatch = useAppDispatch();

  useEffect(() => {
    const status = (s: IBrainStatus): void => {
      dispatch(setBrainStatus(s));
      if (s !== "connected") return;
      // jobs that ran while this window wasn't listening
      void window.electronApi.brain.jobs().then((r) => {
        if (r.ok) dispatch(jobsLoaded(r.data.items));
      });
    };
    void window.electronApi.brain.getStatus().then(status);
    const offStatus = window.electronApi.brain.onStatus(status);
    const offEvent = window.electronApi.brain.onEvent((e) => {
      if (e.event === "settings.changed") {
        dispatch(mergeBrainSettings((e.data as { changed: Partial<IBrainSettings> }).changed));
      }
      dispatch(brainEvent(e));
    });
    return () => {
      offStatus();
      offEvent();
    };
  }, [dispatch]);
}
