import { BrowserWindow, type WebContents } from "electron";
import type { Socket } from "socket.io-client";
import type { IEventPayloadMapping } from "@root/types";
import { ipcWebContentSend } from "../utils/ipcUtils.js";

type SocketConnectionStatePayload = IEventPayloadMapping["socketConnectionState"];
type SocketEventForwardPayload = IEventPayloadMapping["socketEventForward"];
type MicControlPayload = IEventPayloadMapping["onMicControl"];

const MIC_CONTROL_EVENT = "device:mic-control";

class SocketService {
  private socket: Socket | null = null;
  private connectionState: SocketConnectionStatePayload = { connected: false };
  private rendererTargets = new Set<WebContents>();
  private preferredTtsTarget: WebContents | null = null;
  private connecting = false;

  public registerWindow(window: BrowserWindow): void {
    const target = window.webContents;
    if (target.isDestroyed()) {
      return;
    }

    this.rendererTargets.add(target);
    if (!this.preferredTtsTarget || this.preferredTtsTarget.isDestroyed()) {
      this.preferredTtsTarget = target;
    }

    const setPreferredTarget = () => {
      if (!target.isDestroyed()) {
        this.preferredTtsTarget = target;
      }
    };

    window.on("focus", setPreferredTarget);
    window.on("show", setPreferredTarget);
    target.once("destroyed", () => {
      window.off("focus", setPreferredTarget);
      window.off("show", setPreferredTarget);
      this.rendererTargets.delete(target);
      if (this.preferredTtsTarget === target) {
        this.preferredTtsTarget = null;
      }
    });

    this.sendConnectionStateTo(target);
  }

  public getConnectionState(): SocketConnectionStatePayload {
    return this.connectionState;
  }

  public async connect(): Promise<void> {
    if (this.socket?.connected || this.connecting) {
      return;
    }

    this.connecting = true;

    try {
      const token = await this.getAccessToken();
      if (!token) {
        this.connecting = false;
        this.updateConnectionState({
          connected: false,
          reason: "missing_access_token",
        });
        return;
      }

      if (this.socket) {
        this.socket.removeAllListeners();
        this.socket.disconnect();
      }

      const { io } = await import("socket.io-client");
      const newSocket = io(this.resolveSocketUrl(), {
        path: "/socket.io",
        transports: ["websocket", "polling"],
        withCredentials: true,
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        autoConnect: false,
        auth: { token },
      });

      this.socket = newSocket;
      this.bindSocketEvents(newSocket);
      newSocket.connect();
    } catch (error) {
      this.connecting = false;
      const message =
        error instanceof Error ? error.message : "unknown_connection_error";
      this.updateConnectionState({
        connected: false,
        reason: message,
      });
      console.error("❌ [SocketService] Failed to initialize socket:", error);
    }
  }

  public disconnect(reason = "manual_disconnect"): void {
    this.connecting = false;

    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.disconnect();
      this.socket = null;
    }

    this.updateConnectionState({ connected: false, reason });
  }

  public async emit(event: string, args: unknown[] = []): Promise<void> {
    const activeSocket = this.socket;
    if (!activeSocket || !activeSocket.connected) {
      throw new Error("socket_not_connected");
    }

    activeSocket.emit(event, ...args);
  }

  private bindSocketEvents(socket: Socket): void {
    socket.on("connect", () => {
      this.connecting = false;
      this.updateConnectionState({
        connected: true,
        socketId: socket.id,
      });
      console.log("✅ [SocketService] Connected:", socket.id);
    });

    socket.on("disconnect", (reason: string) => {
      this.connecting = false;
      this.updateConnectionState({
        connected: false,
        reason,
      });
      console.log("🔌 [SocketService] Disconnected:", reason);
    });

    socket.on("connect_error", (error: Error) => {
      this.connecting = false;
      this.updateConnectionState({
        connected: false,
        reason: error.message,
      });
      console.error("❌ [SocketService] Connect error:", error.message);
    });

    socket.onAny((eventName, ...args) => {
      const data = args.length <= 1 ? args[0] : args;

      if (eventName === MIC_CONTROL_EVENT) {
        this.handleMicControlEvent(data);
        return;
      }

      this.broadcastSocketEvent({ event: eventName, data });
    });

    socket.io.on("reconnect_attempt", async () => {
      try {
        const freshToken = await this.getAccessToken();
        if (!freshToken) {
          return;
        }

        const opts = socket.io.opts as { auth?: Record<string, unknown> };
        if (!opts.auth) {
          opts.auth = {};
        }
        opts.auth.token = freshToken;
      } catch (error) {
        console.error("❌ [SocketService] Failed to refresh reconnect token:", error);
      }
    });
  }

  private async getAccessToken(): Promise<string | null> {
    const { getToken } = await import("./TokenManager.js");
    return getToken("access_token");
  }

  private resolveSocketUrl(): string {
    const explicitSocketUrl = process.env.VITE_API_SOCKET_URL;
    if (explicitSocketUrl) {
      return explicitSocketUrl;
    }

    const apiBaseUrl = process.env.VITE_API_BASE_URL;
    if (apiBaseUrl) {
      return apiBaseUrl.replace(/\/api\/v1\/?$/i, "");
    }

    return "http://127.0.0.1:8000";
  }

  private updateConnectionState(nextState: SocketConnectionStatePayload): void {
    this.connectionState = nextState;
    this.broadcastConnectionState();
  }

  private broadcastConnectionState(): void {
    for (const target of this.rendererTargets) {
      if (target.isDestroyed()) {
        this.rendererTargets.delete(target);
        continue;
      }

      ipcWebContentSend("socketConnectionState", target, this.connectionState);
    }
  }

  private sendConnectionStateTo(target: WebContents): void {
    if (target.isDestroyed()) {
      return;
    }

    ipcWebContentSend("socketConnectionState", target, this.connectionState);
  }

  private broadcastSocketEvent(payload: SocketEventForwardPayload): void {
    if (this.isSingleTargetTtsEvent(payload.event)) {
      const target = this.resolveTtsTarget();
      if (target) {
        ipcWebContentSend("socketEventForward", target, payload);
      }
      return;
    }

    for (const target of this.rendererTargets) {
      if (target.isDestroyed()) {
        this.rendererTargets.delete(target);
        continue;
      }

      ipcWebContentSend("socketEventForward", target, payload);
    }
  }

  private handleMicControlEvent(data: unknown): void {
    const payload = this.normalizeMicControlPayload(data);
    if (!payload) {
      console.warn("⚠️ [SocketService] Ignoring invalid mic control payload:", data);
      return;
    }

    console.log(
      `🎤 [SocketService] Mic control received: ${payload.action} (${payload.source ?? "socket"})`,
    );

    for (const target of this.rendererTargets) {
      if (target.isDestroyed()) {
        this.rendererTargets.delete(target);
        continue;
      }

      ipcWebContentSend("onMicControl", target, payload);
    }
  }

  private normalizeMicControlPayload(data: unknown): MicControlPayload | null {
    if (!data || typeof data !== "object") {
      return null;
    }

    const candidate = data as Partial<MicControlPayload>;
    const rawAction = typeof candidate.action === "string" ? candidate.action.trim().toLowerCase() : "";
    if (rawAction !== "mute" && rawAction !== "unmute" && rawAction !== "toggle") {
      return null;
    }

    const source =
      typeof candidate.source === "string" && candidate.source.trim().length > 0
        ? candidate.source.trim()
        : "socket";

    return {
      action: rawAction,
      source,
    };
  }

  private isSingleTargetTtsEvent(eventName: string): boolean {
    return (
      eventName === "tts-start" ||
      eventName === "tts-chunk" ||
      eventName === "tts-end" ||
      eventName === "tts-interrupt" ||
      eventName === "response-tts"
    );
  }

  private resolveTtsTarget(): WebContents | null {
    const focused = BrowserWindow.getFocusedWindow()?.webContents ?? null;
    if (focused && !focused.isDestroyed() && this.rendererTargets.has(focused)) {
      this.preferredTtsTarget = focused;
      return focused;
    }

    if (
      this.preferredTtsTarget &&
      !this.preferredTtsTarget.isDestroyed() &&
      this.rendererTargets.has(this.preferredTtsTarget)
    ) {
      return this.preferredTtsTarget;
    }

    for (const candidate of this.rendererTargets) {
      if (!candidate.isDestroyed()) {
        this.preferredTtsTarget = candidate;
        return candidate;
      }
    }

    this.preferredTtsTarget = null;
    return null;
  }
}

export const socketService = new SocketService();
