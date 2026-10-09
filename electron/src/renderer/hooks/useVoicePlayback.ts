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

/** True while Spark's voice is playing: the ear treats speech as a barge-in only then. */
export function isSpeaking(): boolean {
  return speaking;
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
    let ctx: AudioContext | null = null;

    const playNext = (): void => {
      if (current) return;
      const next = queue.shift();
      speaking = next !== undefined;
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
      speaking = false;
    };

    const cue = (kind: "heard" | "done" | "error"): void => {
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
          cue(event.cue);
          return;
        case "stop":
          stop();
          return;
      }
    });
    return () => {
      off();
      stop();
      void ctx?.close();
    };
  }, []);
}
