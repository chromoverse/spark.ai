import { createContext, useContext } from "react";
import type { SocketEvents } from "@shared/socket.types";

// Context + hook live apart from the provider component so Fast Refresh can hot-swap it.

export type TypedEmit = <K extends keyof SocketEvents>(
  event: K,
  ...args: Parameters<SocketEvents[K]>
) => void;

export type TypedOn = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K],
) => void;

export type TypedOff = <K extends keyof SocketEvents>(
  event: K,
  callback?: SocketEvents[K],
) => void;

export type TypedOnce = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K],
) => void;

export interface SocketBridgeHandle {
  id?: string;
}

export interface SocketContextType {
  socket: SocketBridgeHandle | null;
  isConnected: boolean;
  emit: TypedEmit;
  on: TypedOn;
  off: TypedOff;
  once: TypedOnce;
}

export const SocketContext = createContext<SocketContextType | undefined>(undefined);

export const useSocket = (): SocketContextType => {
  const context = useContext(SocketContext);
  if (context === undefined) {
    throw new Error("useSocket must be used within a SocketProvider");
  }
  return context;
};
