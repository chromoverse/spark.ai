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
  ipcMainHandle("voiceStop", () => result(() => voiceLoop.stop().then(() => ({ stopped: true }))));
  ipcMainHandle("enginesGet", () => result(() => voiceLoop.engines()));
  ipcMainHandle("enginesBenchmark", () => result(() => voiceLoop.benchmark()));
}
