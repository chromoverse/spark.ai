import { BrowserWindow } from "electron";
import crypto from "node:crypto";
import type { IEnginesInfo, IVoiceEvent, IVoiceSendResult } from "@root/types";
import { bodyBridge } from "./BodyBridge.js";
import { BRAIN_URL, brainAuth } from "./BrainAuth.js";
import { brainSocket } from "./BrainSocket.js";

// The device half of the voice loop (docs/REDESIGN.md §4.1, §26.4 A–C), in the main process:
// a signal goes to the body's tier 0 first, then to the brain; reply sentences go to the body's
// mouth; tool calls run on the body's hands; audio and cues go to one window to play.

interface ReflexResult {
  handled: boolean;
  intent?: string;
  slots?: Record<string, unknown>;
  result?: Record<string, unknown>;
  interrupt?: boolean;
  record?: boolean;
  chime?: boolean;
}

interface BodyHello {
  capabilities: string[];
  hardware: Record<string, unknown>;
  engine_plan: Record<string, unknown>;
}

const NOT_CONNECTED = "I can't reach my brain right now. I'll keep trying.";
const RELINK_MS = 10 * 60_000; // access tokens live 15 min

/** Audio plays in exactly one window: the AI panel when it's open, else the main window. */
function voiceWindow(): BrowserWindow | null {
  const wins = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed() && !w.webContents.isDestroyed());
  return wins.find((w) => w.isVisible() && w.webContents.getURL().includes("ai-panel")) ?? wins.find((w) => w.isVisible()) ?? wins[0] ?? null;
}

function toVoiceWindow(event: IVoiceEvent): void {
  voiceWindow()?.webContents.send("voiceEvent", event);
}

function broadcast(channel: "enginePlan" | "bodyStatus", payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.webContents.isDestroyed()) win.webContents.send(channel, payload);
  }
}

class VoiceLoop {
  private started = false;
  private sentenceSeq = new Map<string, number>();

  start(): void {
    if (this.started) return;
    this.started = true;
    bodyBridge.onNotify((method, params) => void this.fromBody(method, params));
    bodyBridge.onStatus((status) => broadcast("bodyStatus", status));
    brainSocket.onEvent((event, data) => void this.fromBrain(event, data as Record<string, unknown>));
    brainSocket.setHelloInfo(async () => {
      const hello = await bodyBridge.call<BodyHello>("hello");
      return { capabilities: hello.capabilities, hardware: hello.hardware };
    });
    bodyBridge.start();
    setInterval(() => {
      if (brainSocket.getStatus() === "connected") void this.linkBody();
    }, RELINK_MS);
  }

  /** Cloud voice engines (Groq Orpheus via the brain proxy) need the brain URL and a fresh
   *  access token; the body keeps them in memory only. */
  private async linkBody(): Promise<void> {
    try {
      const token = await brainAuth.getAccessToken();
      await bodyBridge.call("auth.set", { brain_url: BRAIN_URL, access_token: token });
    } catch (err) {
      console.warn("[voice] couldn't link the body to the brain", err);
    }
  }

  stopAll(): void {
    bodyBridge.stop();
  }

  /** A typed or transcribed utterance. Tier 0 on the device first; the brain only if unsure. */
  async send(text: string, source: "text" | "voice" = "text"): Promise<IVoiceSendResult> {
    const signalId = crypto.randomUUID().replaceAll("-", "");
    const utcOffsetMin = -new Date().getTimezoneOffset();
    let local: ReflexResult = { handled: false };
    try {
      local = await bodyBridge.call<ReflexResult>("reflex.handle", { text }, 5_000);
    } catch (err) {
      console.warn("[voice] tier 0 unavailable, asking the brain", err);
    }
    if (local.handled) {
      if (local.interrupt) {
        toVoiceWindow({ kind: "stop" });
        await brainSocket.emit("signal.interrupt", {});
        return { signalId, tier: 0, handled: true };
      }
      if (local.chime) toVoiceWindow({ kind: "cue", cue: "done", signalId });
      if (local.record !== false) {
        const ack = await brainSocket.emit("signal.handled_locally", {
          signal_id: signalId,
          text,
          intent: local.intent,
          slots: local.slots ?? {},
          result: local.result,
          utc_offset_min: utcOffsetMin,
        });
        const tier = (ack?.data as { tier?: number } | undefined)?.tier ?? 0;
        return { signalId, tier, handled: tier === 0 };
      }
      return { signalId, tier: 0, handled: true };
    }
    const ack = await brainSocket.emit("signal.final", {
      signal_id: signalId,
      text,
      source,
      utc_offset_min: utcOffsetMin,
    });
    if (!ack?.ok) {
      // §19.2: say it out loud even without the brain
      void bodyBridge.call("tts.speak", { utt_id: `${signalId}:offline`, text: NOT_CONNECTED }).catch(() => undefined);
      return { signalId, tier: null, handled: false, error: NOT_CONNECTED };
    }
    return { signalId, tier: (ack.data as { tier: number }).tier, handled: false };
  }

  /** Barge-in or the stop button: silence now, then tell the brain. */
  async stop(): Promise<void> {
    toVoiceWindow({ kind: "stop" });
    await bodyBridge.call("tts.stop").catch(() => undefined);
    await brainSocket.emit("signal.interrupt", {});
  }

  async engines(): Promise<IEnginesInfo> {
    const status = bodyBridge.getStatus();
    if (status !== "ready") return { bodyStatus: status, plan: null };
    return { bodyStatus: status, plan: await bodyBridge.call("engine.plan") };
  }

  async benchmark(): Promise<IEnginesInfo> {
    await bodyBridge.call("fitness.run", {}, 120_000);
    return this.engines();
  }

  private async fromBrain(event: string, data: Record<string, unknown>): Promise<void> {
    if (event === "$connected") {
      await this.linkBody();
      const plan = await bodyBridge.call<Record<string, unknown>>("engine.plan").catch(() => null);
      if (plan) {
        const { reasons: _r, history: _h, ...wire } = plan;
        await brainSocket.emit("device.engine_plan", wire);
      }
      return;
    }
    if (event === "reply.delta" && data.speak && typeof data.text === "string" && data.text) {
      const signalId = String(data.signal_id);
      const n = (this.sentenceSeq.get(signalId) ?? 0) + 1;
      this.sentenceSeq.set(signalId, n);
      if (this.sentenceSeq.size > 50) this.sentenceSeq.delete(this.sentenceSeq.keys().next().value as string);
      await bodyBridge
        .call("tts.speak", { utt_id: `${signalId}:${n}`, text: data.text, tone: data.tone ?? null })
        .catch((err: unknown) => console.warn("[voice] tts.speak failed", err));
      return;
    }
    if (event === "reply.cue") {
      toVoiceWindow({ kind: "cue", cue: data.kind as "heard" | "done" | "error", signalId: String(data.signal_id) });
      return;
    }
    if (event === "tool.call") {
      const callId = String(data.call_id);
      const timeoutMs = Math.max(1, Number(data.timeout_s) || 5) * 1000;
      let result: Record<string, unknown>;
      try {
        result = await bodyBridge.call("tool.run", { tool: data.tool, input: data.input }, timeoutMs);
      } catch {
        result = { ok: false, error: { code: "body_down", message: "The device's tool runner isn't available right now." } };
      }
      await brainSocket.emit("tool.result", { call_id: callId, ...result, artifacts: [] });
    }
  }

  private async fromBody(method: string, params: Record<string, unknown>): Promise<void> {
    switch (method) {
      case "mouth.audio":
        toVoiceWindow({ kind: "audio", uttId: String(params.utt_id), seq: Number(params.seq), mime: String(params.mime), data: String(params.data) });
        return;
      case "mouth.done":
        toVoiceWindow({ kind: "done", uttId: String(params.utt_id), ok: Boolean(params.ok) });
        return;
      case "watchdog.incident": {
        const { utt_id: _u, ...incident } = params;
        await brainSocket.emit("engine.incident", incident);
        return;
      }
      case "engine.plan":
        broadcast("enginePlan", params);
        await brainSocket.emit("device.engine_plan", params);
        return;
    }
  }
}

export const voiceLoop = new VoiceLoop();
