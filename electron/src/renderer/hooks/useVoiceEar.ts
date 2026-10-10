import { useCallback, useEffect, useRef, useState } from "react";
import { earcon, isSpeaking, lastSpokeAt } from "./useVoicePlayback";

// The ear's front half (R1): mic + Silero VAD in the renderer (vad-web, already used by v1),
// with Chromium's echo cancellation removing Spark's own voice. Each endpointed utterance goes to
// the body's STT plan, then into the voice loop. Speech while Spark talks is a barge-in.
// Wake word: unless Spark is mid-conversation, the body only passes on utterances that hold
// "Hey Spark" (spotted on the device; the rest is dropped there, never transcribed or sent).

const FOLLOW_UP_MS = 8_000; // after Spark talks, or after a bare "Hey Spark": no wake word needed

const ORT_WASM_BASE_PATH = import.meta.env.DEV
  ? "/node_modules/onnxruntime-web/dist/"
  : "../node_modules/onnxruntime-web/dist/";
const VAD_BASE_ASSET_PATH = import.meta.env.DEV
  ? "/node_modules/@ricky0123/vad-web/dist/"
  : "../node_modules/@ricky0123/vad-web/dist/";

interface MicVadLike {
  start: () => void | Promise<void>;
  pause: () => void;
  destroy: () => void | Promise<void>;
}

interface VadModuleLike {
  MicVAD: { new: (options: Record<string, unknown>) => Promise<MicVadLike> };
}

function pcm16Base64(audio: Float32Array): string {
  const pcm = new Int16Array(audio.length);
  for (let i = 0; i < audio.length; i++) {
    const v = Math.max(-1, Math.min(1, audio[i]));
    pcm[i] = v < 0 ? v * 32768 : v * 32767;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

export interface Heard {
  text: string;
  signalId: string;
  tier: number | null;
}

export function useVoiceEar(
  onHeard: (heard: Heard) => void,
  wakeWord = true,
): {
  listening: boolean;
  toggle: () => void;
  error: string | null;
} {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const vadRef = useRef<MicVadLike | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const onHeardRef = useRef(onHeard);
  const wakeRef = useRef(wakeWord);
  const armedUntil = useRef(0);
  useEffect(() => {
    onHeardRef.current = onHeard;
    wakeRef.current = wakeWord;
  }, [onHeard, wakeWord]);

  const stop = useCallback(() => {
    void vadRef.current?.destroy();
    vadRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setListening(false);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const { MicVAD } = (await import("@ricky0123/vad-web")) as unknown as VadModuleLike;
      const vad = await MicVAD.new({
        startOnLoad: false,
        positiveSpeechThreshold: 0.75,
        negativeSpeechThreshold: 0.55,
        minSpeechMs: 300,
        redemptionMs: 250, // endpoint after ~250 ms of silence (REDESIGN §4.2)
        preSpeechPadMs: 120,
        baseAssetPath: VAD_BASE_ASSET_PATH,
        onnxWASMBasePath: ORT_WASM_BASE_PATH,
        getStream: async () => stream,
        onSpeechStart: () => {
          if (isSpeaking()) void window.electronApi.voice.stop(); // barge-in
        },
        onSpeechEnd: (audio: Float32Array) => {
          const endedAt = Date.now();
          const followUp = endedAt - lastSpokeAt() < FOLLOW_UP_MS || endedAt < armedUntil.current;
          const needWake = wakeRef.current && !followUp;
          void window.electronApi.voice.hear(pcm16Base64(audio), endedAt, needWake).then((r) => {
            if (!r.ok) setError(r.error.message);
            else if (r.data.heard) {
              armedUntil.current = 0;
              onHeardRef.current({ text: r.data.heard, signalId: r.data.signalId, tier: r.data.tier });
            } else if (r.data.wake === true) {
              armedUntil.current = Date.now() + FOLLOW_UP_MS; // just "Hey Spark": listening now
              earcon("heard");
            }
          });
        },
      });
      vadRef.current = vad;
      await vad.start();
      setListening(true);
    } catch (err) {
      console.error("[ear] mic start failed", err);
      setError("I can't hear you: the microphone didn't start. Check its permission.");
      stop();
    }
  }, [stop]);

  useEffect(() => stop, [stop]);

  const toggle = useCallback(() => {
    if (vadRef.current) stop();
    else void start();
  }, [start, stop]);

  return { listening, toggle, error };
}
