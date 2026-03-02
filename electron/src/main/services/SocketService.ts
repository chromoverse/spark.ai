import type { BrowserWindow, WebContents } from "electron";
import type { Socket } from "socket.io-client";
import type { IEventPayloadMapping } from "@root/types";
import { ipcWebContentSend } from "../utils/ipcUtils.js";

type SocketConnectionStatePayload = IEventPayloadMapping["socketConnectionState"];
type SocketEventForwardPayload = IEventPayloadMapping["socketEventForward"];

class SocketService {
  private socket: Socket | null = null;
  private connectionState: SocketConnectionStatePayload = { connected: false };
  private rendererTargets = new Set<WebContents>();
  private connecting = false;

  public registerWindow(window: BrowserWindow): void {
    const target = window.webContents;
    if (target.isDestroyed()) {
      return;
    }

    this.rendererTargets.add(target);
    target.once("destroyed", () => {
      this.rendererTargets.delete(target);
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
    for (const target of this.rendererTargets) {
      if (target.isDestroyed()) {
        this.rendererTargets.delete(target);
        continue;
      }

      ipcWebContentSend("socketEventForward", target, payload);
    }
  }
}

export const socketService = new SocketService();
