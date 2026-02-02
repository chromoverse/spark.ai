// contexts/SocketContext.tsx

import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { io, Socket } from "socket.io-client";
import type { RegisteredPayload, SocketEvents } from "@shared/socket.types";
import type { IUser } from "@shared/user.types";
import { useAppDispatch } from "../store/hooks";
import { setServerOffline, setServerOnline } from "@/store/features/localState/localSlice";
import { tokenRefreshManager } from "@/lib/auth/tokenRefreshManager";
import { toast } from "sonner";

// Type-safe emit function
type TypedEmit = <K extends keyof SocketEvents>(
  event: K,
  ...args: Parameters<SocketEvents[K]>
) => void;

// Type-safe on function
type TypedOn = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K]
) => void;

// Type-safe off function
type TypedOff = <K extends keyof SocketEvents>(
  event: K,
  callback?: SocketEvents[K]
) => void;

// Type-safe once function
type TypedOnce = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K]
) => void;

interface SocketContextType {
  socket: Socket | null;
  isConnected: boolean;
  emit: TypedEmit;
  on: TypedOn;
  off: TypedOff;
  once: TypedOnce;
}

interface SocketProviderProps {
  children: ReactNode;
  value: IUser | null; // currentUser
}

// ==================== CONTEXT ====================

const SocketContext = createContext<SocketContextType | undefined>(undefined);

// ==================== PROVIDER ====================

export const SocketProvider = ({
  children,
  value: currentUser,
}: SocketProviderProps) => {
  const dispatch = useAppDispatch();
  const socketRef = useRef<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const connectionAttemptRef = useRef(0);
  const maxConnectionAttempts = 3;

  const socketUrl =
    import.meta.env.VITE_API_SOCKET_URL || "http://127.0.0.1:8000";

  console.log("Socket URL:", socketUrl);

  const connectSocket = async () => {
    if (!currentUser) {
      console.log("⏳ No user, skipping socket connection");
      return;
    }

    if (socketRef.current?.connected) {
      console.log("Socket already connected, skipping...");
      return;
    }

    try {
      connectionAttemptRef.current += 1;
      console.log(`🔌 Attempting socket connection (attempt ${connectionAttemptRef.current})...`);

      // ✅ Get valid token from token manager
      const validToken = await tokenRefreshManager.getValidAccessToken();
      console.log("✅ Got valid token, connecting to socket...");

      // ========= CREATE SOCKET.IO INSTANCE =========
      const newSocket = io(socketUrl, {
        path: "/socket.io",
        transports: ["websocket", "polling"],
        withCredentials: true,
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        autoConnect: true,
        auth: {
          token: validToken, // ✅ Fresh token from token manager
        },
      });

      socketRef.current = newSocket;

      // ========= CONNECTION EVENTS =========

      newSocket.on("connect", () => {
        console.log("✅ Socket connected:", newSocket.id);
        connectionAttemptRef.current = 0; // Reset attempt counter
        
        // Register user (backward compatibility)
        newSocket.emit("register_user", currentUser._id);
        
        dispatch(setServerOnline());
        setIsConnected(true);
      });

      newSocket.on("registered", (data: RegisteredPayload) => {
        console.log("🟢 User registered on server:", data.userId);
      });

      newSocket.on("connect_error", async (err: Error) => {
        console.error("❌ Socket connection error:", err.message);

        // Check if error is due to expired token
        if (err.message.includes("expired") || err.message.includes("Signature has expired")) {
          console.log("🔄 Token expired during connection, attempting refresh...");

          // Disconnect current socket
          if (socketRef.current) {
            socketRef.current.disconnect();
            socketRef.current = null;
          }

          // Only retry if we haven't exceeded max attempts
          if (connectionAttemptRef.current < maxConnectionAttempts) {
            try {
              // Force token refresh
              await tokenRefreshManager.refreshAccessToken();
              
              // Retry connection with new token
              setTimeout(() => {
                connectSocket();
              }, 1000);
              
              return;
            } catch (refreshError) {
              console.error("❌ Token refresh failed:", refreshError);
              toast.error("Session expired. Please login again.");
            }
          } else {
            console.error("❌ Max connection attempts reached");
            toast.error("Unable to connect. Please refresh the page.");
          }
        }

        dispatch(setServerOffline());
        setIsConnected(false);
      });

      newSocket.on("disconnect", (reason: string) => {
        console.log("🔌 Socket disconnected:", reason);
        dispatch(setServerOffline());
        setIsConnected(false);

        // If server disconnected due to auth issues, allow reconnection attempts
        if (reason === "io server disconnect") {
          console.log("⚠️ Server disconnected socket, may need token refresh");
          connectionAttemptRef.current = 0;
        }
      });

      newSocket.on("reconnect", async (attemptNumber: number) => {
        console.log("🔄 Reconnected after", attemptNumber, "attempts");
        dispatch(setServerOnline());
        setIsConnected(true);
      });

      // ✅ Refresh token before reconnection attempts
      newSocket.io.on("reconnect_attempt", async () => {
        console.log("🔄 Attempting to reconnect...");

        try {
          // Get fresh token for reconnection
          const freshToken = await tokenRefreshManager.getValidAccessToken();
          
          // Update auth with fresh token
          const manager = newSocket.io as any;
          if (manager.opts && manager.opts.auth) {
            manager.opts.auth.token = freshToken;
          }
          
          console.log("✅ Updated auth token for reconnection");
        } catch (error) {
          console.error("❌ Failed to refresh token for reconnection:", error);
        }
      });

    } catch (error) {
      console.error("❌ Failed to connect socket:", error);

      if (connectionAttemptRef.current < maxConnectionAttempts) {
        console.log(`⏳ Retrying connection in 2 seconds...`);
        setTimeout(() => {
          connectSocket();
        }, 2000);
      } else {
        toast.error("Unable to establish connection. Please refresh the page.");
      }
    }
  };

  // ========= EFFECT: Connect Socket =========

  useEffect(() => {
    if (!currentUser) {
      console.log("No user, skipping socket connection");
      return;
    }

    connectSocket();

    // Cleanup on unmount
    return () => {
      if (socketRef.current) {
        console.log("👋 Disconnecting socket");
        socketRef.current.disconnect();
        socketRef.current = null;
        dispatch(setServerOffline());
      }
    };
  }, [currentUser?._id, socketUrl]);

  // ========= TYPE-SAFE WRAPPER FUNCTIONS =========

  const emit: TypedEmit = (event, ...args) => {
    if (socketRef.current && isConnected) {
      socketRef.current.emit(event as string, ...args);
    } else {
      console.warn(
        `Cannot emit "${String(event)}": socket ${
          !socketRef.current ? "not initialized" : "not connected"
        }`
      );
    }
  };

  const on: TypedOn = (event, callback) => {
    if (socketRef.current) {
      socketRef.current.on(event as string, callback as any);
    } else {
      console.warn(`Cannot listen to "${String(event)}": socket not initialized`);
    }
  };

  const off: TypedOff = (event, callback) => {
    if (socketRef.current) {
      if (callback) {
        socketRef.current.off(event as string, callback as any);
      } else {
        socketRef.current.off(event as string);
      }
    }
  };

  const once: TypedOnce = (event, callback) => {
    if (socketRef.current) {
      socketRef.current.once(event as string, callback as any);
    } else {
      console.warn(`Cannot listen once to "${String(event)}": socket not initialized`);
    }
  };

  const contextValue: SocketContextType = {
    socket: socketRef.current,
    isConnected,
    emit,
    on,
    off,
    once,
  };

  if (!currentUser) return <>{children}</>;

  return (
    <SocketContext.Provider value={contextValue}>
      {children}
    </SocketContext.Provider>
  );
};

// ==================== HOOK ====================

export const useSocket = (): SocketContextType => {
  const context = useContext(SocketContext);

  if (context === undefined) {
    throw new Error("useSocket must be used within a SocketProvider");
  }

  return context;
};
