import { app } from "electron";
import type { IBrainResult } from "@root/types";
import { ipcMainHandle } from "../utils/ipcUtils.js";
import { BodyError } from "../services/BodyBridge.js";
import { voiceLoop } from "../services/VoiceLoop.js";

async function result<T>(fn: () => Promise<T>): Promise<IBrainResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (err) {
    if (err instanceof BodyError) return { ok: false, error: { code: err.code, message: err.message } };
    console.error("[voice] ipc failed", err);
    return { ok: false, error: { code: "internal", message: "Something went sideways. Try again in a moment." } };
  }
}

export function registerVoiceHandlers(): void {
  voiceLoop.start();
  app.on("will-quit", () => voiceLoop.stopAll());

  ipcMainHandle("voiceSend", (_event, payload) =>
    result(async () => {
      const text = (payload as { text?: unknown } | null)?.text;
      if (typeof text !== "string" || !text.trim() || text.length > 2000) {
        throw new BodyError("invalid_input", "Say or type something first.");
      }
      return voiceLoop.send(text.trim());
    }),
  );
  ipcMainHandle("voiceHear", (_event, payload) =>
    result(async () => {
      const { pcm16, endedAt, wake } = (payload ?? {}) as { pcm16?: unknown; endedAt?: unknown; wake?: unknown };
      // ≤ ~60 s of 16 kHz PCM16, base64
      if (typeof pcm16 !== "string" || !pcm16 || pcm16.length > 2_600_000 || typeof endedAt !== "number") {
        throw new BodyError("invalid_input", "That clip didn't come through. Try again.");
      }
      return voiceLoop.hear(pcm16, endedAt, wake === true);
    }),
  );
  ipcMainHandle("voiceFirstAudio", (_event, payload) => {
    const { signalId, at } = (payload ?? {}) as { signalId?: unknown; at?: unknown };
    if (typeof signalId === "string" && typeof at === "number") void voiceLoop.firstAudio(signalId, at);
    return { ok: true };
  });
  // Spark plays in one window, the ear may run in another: every window learns when it talks
  ipcMainHandle("voiceSpeaking", (_event, payload) => {
    voiceLoop.speakingChanged((payload as { speaking?: unknown } | null)?.speaking === true);
    return { ok: true };
  });
  ipcMainHandle("voiceStop", () => result(() => voiceLoop.stop().then(() => ({ stopped: true }))));
  ipcMainHandle("enginesGet", () => result(() => voiceLoop.engines()));
  ipcMainHandle("enginesBenchmark", () => result(() => voiceLoop.benchmark()));
}
