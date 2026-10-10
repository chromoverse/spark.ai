import { useCallback, useEffect, useRef, useState } from "react";
import type { IBrainResult, IVoiceHeard } from "@root/types";
import { earcon, isSpeaking, lastAskedAt, lastSpokeAt } from "./useVoicePlayback";

// The ear's front half (R1): mic + Silero VAD in the renderer (vad-web, already used by v1),
// with Chromium's echo cancellation removing Spark's own voice. Each endpointed utterance goes to
// the body's STT plan, then into the voice loop. Speech while Spark talks is a barge-in.
// Wake word: unless Spark is mid-conversation, the body only passes on utterances that hold
// "Hey Spark" (spotted on the device; the rest is dropped there, never transcribed or sent).
// Mid-conversation is bounded: after a "Hey Spark" request, two follow-ups may skip the phrase,
// each within 6 s of Spark finishing. Unbounded follow-ups let room voices keep a conversation
// going on their own (owner's mic test, 2026-10-10: 6–8 strangers' lines in a row). When Spark
// ends on a question, one answer needs no wake word either, cap or not: "yes, do it" was ignored
// (owner's mic test, same day).
// Speculative start (REDESIGN §4.2): after 250 ms of silence the utterance is transcribed and the
// brain starts on the reply; it plays only once the silence reaches 700 ms. Speech that resumes in
// between cancels that turn and is merged and heard again, so a pause mid-sentence doesn't split
// it (the owner's first mic test split sentences at 250 ms pauses).

const CANDIDATE_MS = 250;
const ENDPOINT_MS = 700;
const FOLLOW_UP_MS = 6_000;
const MAX_FOLLOW_UPS = 2;
const ARMED_MS = 8_000; // after a bare "Hey Spark": the command may take a moment
const ANSWER_MS = 8_000; // after Spark asks something: an answer may take a moment

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

/** An utterance at its endpoint candidate: transcribing, not run yet. */
interface Pending {
  audio: Float32Array;
  armed: boolean;
  followUp: "answer" | "turn" | null; // what lets it skip the wake word
  needWake: boolean;
  heard: Promise<IBrainResult<IVoiceHeard>>;
  timer: number | null; // commits at ENDPOINT_MS; cleared while speech resumes
}

/** Speech resumed or the mic stopped: the candidate's speculative brain turn is cancelled. */
function drop(p: Pending): void {
  void p.heard.then((r) => {
    if (r.ok && r.data.signalId) void window.electronApi.voice.drop(r.data.signalId);
  });
}

function concat(a: Float32Array, b: Float32Array): Float32Array {
  const out = new Float32Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
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
  status: string | null;
} {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const vadRef = useRef<MicVadLike | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const onHeardRef = useRef(onHeard);
  const wakeRef = useRef(wakeWord);
  const armedUntil = useRef(0);
  const followUps = useRef(0); // left in this exchange
  const pending = useRef<Pending | null>(null);
  const answered = useRef(0); // the question (lastAskedAt) already answered
  const inExchange = (): Pending["followUp"] => {
    const quiet = Date.now() - lastSpokeAt();
    const asked = lastAskedAt();
    if (asked > answered.current && quiet < ANSWER_MS) return "answer";
    return followUps.current > 0 && quiet < FOLLOW_UP_MS ? "turn" : null;
  };
  useEffect(() => {
    onHeardRef.current = onHeard;
    wakeRef.current = wakeWord;
  }, [onHeard, wakeWord]);

  /** The endpoint held (no speech for ENDPOINT_MS): run what the candidate heard. */
  const commit = useCallback(async () => {
    const p = pending.current;
    if (!p) return;
    pending.current = null;
    if (p.timer !== null) window.clearTimeout(p.timer);
    const r = await p.heard;
    if (!r.ok) {
      setError(r.error.message);
      return;
    }
    const { heard, signalId, wake } = r.data;
    if (heard) {
      // a "Hey Spark" request opens the exchange; each follow-up uses one turn of it
      if (wake === true || p.armed) followUps.current = MAX_FOLLOW_UPS;
      else if (p.followUp === "turn") followUps.current -= 1;
      answered.current = Date.now(); // whatever they said answers Spark's question, if it asked
      armedUntil.current = 0;
      setStatus(null);
      const sent = await window.electronApi.voice.commit(signalId, heard);
      if (!sent.ok) setError(sent.error.message);
      else onHeardRef.current({ text: heard, signalId, tier: sent.data.tier });
    } else if (wake === true) {
      armedUntil.current = Date.now() + ARMED_MS; // just "Hey Spark": listening now
      setStatus("Listening…");
      earcon("heard");
    } else if (wake === false) {
      setStatus("Heard speech without “Hey Spark” first, so I ignored it.");
    }
  }, []);

  const stop = useCallback(() => {
    if (pending.current) {
      if (pending.current.timer !== null) window.clearTimeout(pending.current.timer);
      drop(pending.current);
    }
    pending.current = null;
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
        minSpeechMs: 200, // "yes" and "do it" are ~250 ms
        redemptionMs: CANDIDATE_MS,
        preSpeechPadMs: 120,
        baseAssetPath: VAD_BASE_ASSET_PATH,
        onnxWASMBasePath: ORT_WASM_BASE_PATH,
        getStream: async () => stream,
        onSpeechStart: () => {
          // barge-in only inside an exchange; otherwise "Hey Spark, stop" stops it (tier 0)
          if (isSpeaking() && (!wakeRef.current || inExchange() !== null)) void window.electronApi.voice.stop();
          const p = pending.current;
          if (p?.timer != null) {
            window.clearTimeout(p.timer); // speech resumed: hold the commit
            p.timer = null;
          }
        },
        onVADMisfire: () => {
          // what resumed was too short to be speech (a click, a breath): run what we had.
          // ponytail: a real short word after a pause ("…, now") is lost; vad-web gives no audio
          // for misfires. Accumulate frames in onFrameProcessed if that shows up in use.
          if (pending.current?.timer === null) void commit();
        },
        onSpeechEnd: (audio: Float32Array) => {
          const endedAt = Date.now();
          const prev = pending.current;
          const armed = prev?.armed ?? endedAt < armedUntil.current;
          const followUp = prev ? prev.followUp : inExchange();
          const needWake = prev?.needWake ?? (wakeRef.current && !armed && !followUp);
          if (prev) drop(prev);
          const merged = prev ? concat(prev.audio, audio) : audio;
          pending.current = {
            audio: merged,
            armed,
            followUp,
            needWake,
            heard: window.electronApi.voice.hear(pcm16Base64(merged), endedAt, needWake),
            timer: window.setTimeout(() => void commit(), ENDPOINT_MS - CANDIDATE_MS),
          };
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
  }, [commit, stop]);

  useEffect(() => stop, [stop]);

  const toggle = useCallback(() => {
    if (vadRef.current) stop();
    else void start();
  }, [start, stop]);

  return { listening, toggle, error, status };
}
