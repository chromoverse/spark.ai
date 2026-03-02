import { ipcMainHandle } from "../utils/ipcUtils.js";
import { socketService } from "../services/SocketService.js";

interface SocketEmitPayload {
  event: string;
  args?: unknown[];
}

export function registerSocketHandlers() {
  ipcMainHandle("socketEmit", async (_event, payload: SocketEmitPayload) => {
    if (!payload || typeof payload.event !== "string" || payload.event.length === 0) {
      return { success: false, error: "invalid_socket_event" };
    }

    try {
      const args = Array.isArray(payload.args) ? payload.args : [];
      await socketService.emit(payload.event, args);
      return { success: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : "socket_emit_failed";
      return { success: false, error: message };
    }
  });

  ipcMainHandle("getSocketConnectionState", () => {
    return socketService.getConnectionState();
  });
}
