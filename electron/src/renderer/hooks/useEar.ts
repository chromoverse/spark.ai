import { useEffect, useState } from "react";

/** The ear lives in the overlay window (useVoiceEar there); any other window shows its state and
 * toggles it through main. */
export function useEar(): { listening: boolean; toggle: () => void } {
  const [listening, setListening] = useState(false);
  useEffect(() => {
    void window.electronApi.voice.earGet().then((s) => setListening(s.listening));
    return window.electronApi.voice.onEarState((s) => setListening(s.listening));
  }, []);
  return { listening, toggle: () => void window.electronApi.voice.toggleEar() };
}
