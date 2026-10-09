import { app, BrowserWindow } from "electron";
import crypto from "node:crypto";
import os from "node:os";
import { io, type Socket } from "socket.io-client";
import type { IBrainStatus, IEventPayloadMapping } from "@root/types";
import { BRAIN_URL, BrainError, brainAuth } from "./BrainAuth.js";

// The one v2 socket to the brain (docs/API.md §3), owned by the main process. Windows get its
// status and events over IPC; they never see a token.

const RETRY_AFTER_OFFLINE_MS = 5_000;

type BrainListener = (event: string, data: unknown) => void;
export interface IHelloInfo {
  capabilities: string[];
  hardware: Record<string, unknown>;
}
export interface IBrainAck {
  ok: boolean;
  data?: unknown;
  error?: { code: string; message: string };
}

function broadcast<K extends "brainStatus" | "brainEvent">(key: K, payload: IEventPayloadMapping[K]): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.webContents.isDestroyed()) win.webContents.send(key, payload);
  }
}

function envelope(payload: Record<string, unknown>): Record<string, unknown> {
  return { v: 2, id: crypto.randomUUID(), ts: Date.now(), trace_id: crypto.randomUUID().replaceAll("-", ""), ...payload };
}

class BrainSocket {
  private socket: Socket | null = null;
  private status: IBrainStatus = "signed_out";
  private listeners = new Set<BrainListener>();
  private helloInfo: (() => Promise<IHelloInfo | null>) | null = null;

  /** Main-process consumers (the voice loop). "$connected" fires after every device.hello. */
  onEvent(fn: BrainListener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** What the body reports about this device; merged into device.hello on every connect. */
  setHelloInfo(fn: () => Promise<IHelloInfo | null>): void {
    this.helloInfo = fn;
  }

  /** Sends a device → brain event; null when offline or the brain didn't ack in time. */
  async emit(event: string, payload: Record<string, unknown>, timeoutMs = 5_000): Promise<IBrainAck | null> {
    const socket = this.socket;
    if (!socket?.connected) return null;
    try {
      return (await socket.timeout(timeoutMs).emitWithAck(event, envelope(payload))) as IBrainAck;
    } catch {
      return null;
    }
  }

  getStatus(): IBrainStatus {
    return this.status;
  }

  async connect(): Promise<void> {
    if (this.socket) return;
    const deviceId = await brainAuth.deviceId();
    if (!deviceId || !(await brainAuth.hasSession())) {
      this.setStatus("signed_out");
      return;
    }
    this.setStatus("connecting");
    const socket = io(`${BRAIN_URL}/v2`, {
      transports: ["websocket"],
      timeout: 10_000,
      reconnectionDelayMax: 10_000,
      // Called on every (re)connect, so a reconnect after 15 minutes gets a fresh token.
      auth: (cb) => {
        brainAuth.getAccessToken().then(
          (token) => cb({ token, device_id: deviceId }),
          () => cb({ token: "", device_id: deviceId }),
        );
      },
    });
    this.socket = socket;

    socket.on("connect", () => {
      this.setStatus("connected");
      void this.hello(socket);
    });
    socket.on("disconnect", (reason) => {
      if (reason === "io client disconnect") return;
      this.setStatus("offline");
      // The brain only drops us when the session ended; reconnecting re-checks via refresh.
      if (reason === "io server disconnect") this.retry(socket, 0);
    });
    socket.on("connect_error", (err: Error & { data?: { code?: string } }) => {
      this.setStatus("offline");
      if (socket.active) return; // transport error: socket.io keeps retrying on its own
      if (err.data?.code !== "unauthorized") {
        this.retry(socket, RETRY_AFTER_OFFLINE_MS);
        return;
      }
      brainAuth.refresh().then(
        () => this.retry(socket, 0),
        (refreshErr: unknown) => {
          if (refreshErr instanceof BrainError && refreshErr.code === "unauthorized") {
            this.disconnect("signed_out");
          } else {
            this.retry(socket, RETRY_AFTER_OFFLINE_MS);
          }
        },
      );
    });
    socket.onAny((event: string, data: unknown) => {
      broadcast("brainEvent", { event, data });
      for (const fn of this.listeners) fn(event, data);
    });
  }

  disconnect(status: IBrainStatus = "signed_out"): void {
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.disconnect();
      this.socket = null;
    }
    this.setStatus(status);
  }

  private retry(socket: Socket, delayMs: number): void {
    setTimeout(() => {
      if (this.socket === socket && !socket.connected) socket.connect();
    }, delayMs);
  }

  private async hello(socket: Socket): Promise<void> {
    const body = await this.helloInfo?.().catch(() => null);
    try {
      const ack = await socket.timeout(5_000).emitWithAck(
        "device.hello",
        envelope({
          platform: process.platform,
          app_version: app.getVersion(),
          capabilities: body?.capabilities ?? [],
          tool_versions: {},
          hardware: body?.hardware ?? {
            arch: process.arch,
            cpus: os.cpus().length,
            ram_gb: Math.round(os.totalmem() / 2 ** 30),
          },
        }),
      );
      if (!ack?.ok) console.warn("[brain] device.hello rejected", ack?.error?.code);
    } catch {
      console.warn("[brain] device.hello timed out");
    }
    for (const fn of this.listeners) fn("$connected", null);
  }

  private setStatus(status: IBrainStatus): void {
    if (this.status === status) return;
    this.status = status;
    broadcast("brainStatus", status);
  }
}

export const brainSocket = new BrainSocket();
