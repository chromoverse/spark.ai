import { useEffect } from "react";
import type { IBrainSettings } from "@root/types";
import { useAppDispatch } from "@/store/hooks";
import { mergeBrainSettings, setBrainStatus } from "@/store/features/brain/brainSlice";

/** Mirrors the main process's brain socket into Redux: connection status and pushed events. */
export function useBrainBridge(): void {
  const dispatch = useAppDispatch();

  useEffect(() => {
    void window.electronApi.brain.getStatus().then((status) => dispatch(setBrainStatus(status)));
    const offStatus = window.electronApi.brain.onStatus((status) => dispatch(setBrainStatus(status)));
    const offEvent = window.electronApi.brain.onEvent(({ event, data }) => {
      if (event === "settings.changed") {
        dispatch(mergeBrainSettings((data as { changed: Partial<IBrainSettings> }).changed));
      }
    });
    return () => {
      offStatus();
      offEvent();
    };
  }, [dispatch]);
}
