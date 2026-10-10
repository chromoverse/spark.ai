import { useEffect } from "react";
import type { IVoiceEvent } from "@root/types";

// Plays what the body's mouth synthesizes, sentence by sentence and in order, plus the earcons
// (docs/REDESIGN.md §4.4). Only the voice window gets these events, so nothing plays twice.
// The first sentence of each signal reports when it actually started playing (the trace, §13).

const CUES: Record<"heard" | "done" | "error", [number, number][]> = {
  heard: [[880, 0.06]],
  done: [[660, 0.07], [990, 0.09]],
  error: [[330, 0.12], [247, 0.16]],
};

let speaking = false;
let spokeAt = 0; // ms epoch when Spark last stopped talking

/** True while Spark's voice is playing: the ear treats speech as a barge-in only then. */
export function isSpeaking(): boolean {
  return speaking;
}

/** When Spark last finished talking: the ear skips the wake word for a follow-up after that. */
export function lastSpokeAt(): number {
  return speaking ? Date.now() : spokeAt;
}

/** Audio plays in one window (often the floating panel) and the ear may listen in another, so
 * the playing window tells main, and main tells every window (voiceSpeakingState). */
function setSpeaking(value: boolean): void {
  if (value === speaking) return;
  speaking = value;
  if (!value) spokeAt = Date.now();
  void window.electronApi.voice.speaking(value);
}

let ctx: AudioContext | null = null;

/** A short earcon (§4.4). Also used by the ear: "heard" when "Hey Spark" alone opens a command. */
export function earcon(kind: "heard" | "done" | "error"): void {
  ctx ??= new AudioContext();
  let t = ctx.currentTime;
  for (const [freq, dur] of CUES[kind]) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.08, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + dur);
    t += dur;
  }
}

function decode(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function useVoicePlayback(): void {
  useEffect(() => {
    const chunks = new Map<string, { mime: string; parts: Uint8Array<ArrayBuffer>[] }>();
    const queue: { url: string; uttId: string }[] = []; // in order
    const reported = new Set<string>();
    let current: HTMLAudioElement | null = null;

    const playNext = (): void => {
      if (current) return;
      const next = queue.shift();
      setSpeaking(next !== undefined);
      if (!next) return;
      const audio = new Audio(next.url);
      current = audio;
      const signalId = next.uttId.split(":")[0];
      audio.onplaying = () => {
        if (reported.has(signalId)) return;
        reported.add(signalId);
        void window.electronApi.voice.firstAudio(signalId, Date.now());
      };
      const finish = (): void => {
        URL.revokeObjectURL(next.url);
        if (current === audio) current = null;
        playNext();
      };
      audio.onended = finish;
      audio.onerror = finish;
      void audio.play().catch(finish);
    };

    const stop = (): void => {
      chunks.clear();
      for (const item of queue.splice(0)) URL.revokeObjectURL(item.url);
      if (current) {
        current.pause();
        current = null;
      }
      setSpeaking(false);
    };

    const off = window.electronApi.voice.onEvent((event: IVoiceEvent) => {
      switch (event.kind) {
        case "audio": {
          const entry = chunks.get(event.uttId) ?? { mime: event.mime, parts: [] };
          entry.parts.push(decode(event.data));
          chunks.set(event.uttId, entry);
          return;
        }
        case "done": {
          const entry = chunks.get(event.uttId);
          chunks.delete(event.uttId);
          // ponytail: whole-sentence blobs; stream through MediaSource if first audio needs it
          if (event.ok && entry) {
            const url = URL.createObjectURL(new Blob(entry.parts, { type: entry.mime }));
            queue.push({ url, uttId: event.uttId });
            playNext();
          }
          return;
        }
        case "cue":
          earcon(event.cue);
          return;
        case "stop":
          stop();
          return;
      }
    });
    const offSpeaking = window.electronApi.voice.onSpeaking((state) => {
      speaking = state.speaking;
      if (!state.speaking) spokeAt = state.at;
    });
    return () => {
      off();
      offSpeaking();
      stop();
      void ctx?.close();
      ctx = null;
    };
  }, []);
}
