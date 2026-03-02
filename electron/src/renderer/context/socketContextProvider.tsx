import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { SocketEvents } from "@shared/socket.types";
import { useAppDispatch } from "../store/hooks";
import {
  setServerOffline,
  setServerOnline,
} from "@/store/features/localState/localSlice";

type TypedEmit = <K extends keyof SocketEvents>(
  event: K,
  ...args: Parameters<SocketEvents[K]>
) => void;

type TypedOn = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K],
) => void;

type TypedOff = <K extends keyof SocketEvents>(
  event: K,
  callback?: SocketEvents[K],
) => void;

type TypedOnce = <K extends keyof SocketEvents>(
  event: K,
  callback: SocketEvents[K],
) => void;

type InternalListener = (...args: unknown[]) => void;

interface SocketBridgeHandle {
  id?: string;
}

interface SocketContextType {
  socket: SocketBridgeHandle | null;
  isConnected: boolean;
  emit: TypedEmit;
  on: TypedOn;
  off: TypedOff;
  once: TypedOnce;
}

interface SocketProviderProps {
  children: ReactNode;
}

interface SocketConnectionStatePayload {
  connected: boolean;
  socketId?: string;
  reason?: string;
}

const SocketContext = createContext<SocketContextType | undefined>(undefined);

export const SocketProvider = ({ children }: SocketProviderProps) => {
  const dispatch = useAppDispatch();

  const [isConnected, setIsConnected] = useState(false);
  const [socketHandle, setSocketHandle] = useState<SocketBridgeHandle | null>(
    null,
  );

  const listenersRef = useRef<Map<string, Set<InternalListener>>>(new Map());

  const updateConnectionState = useCallback(
    (payload: SocketConnectionStatePayload) => {
      if (payload.connected) {
        setIsConnected(true);
        setSocketHandle({ id: payload.socketId });
        dispatch(setServerOnline());
      } else {
        setIsConnected(false);
        setSocketHandle(null);
        dispatch(setServerOffline());
      }
    },
    [dispatch],
  );

  const emitToListeners = useCallback((eventName: string, data: unknown) => {
    const listeners = listenersRef.current.get(eventName);
    if (!listeners || listeners.size === 0) {
      return;
    }

    const args = Array.isArray(data) ? data : [data];
    for (const listener of Array.from(listeners)) {
      try {
        listener(...args);
      } catch (error) {
        console.error(`❌ Socket listener crashed for "${eventName}":`, error);
      }
    }
  }, []);

  useEffect(() => {
    const unsubscribeState = window.electronApi.onSocketConnectionState(
      updateConnectionState,
    );

    const unsubscribeEvents = window.electronApi.onSocketEventForward(
      ({ event, data }) => {
        emitToListeners(event, data);
      },
    );

    void window.electronApi
      .getSocketConnectionState()
      .then(updateConnectionState)
      .catch((error) => {
        console.warn("⚠️ Failed to get initial socket state:", error);
      });

    return () => {
      unsubscribeState();
      unsubscribeEvents();
      listenersRef.current.clear();
    };
  }, [emitToListeners, updateConnectionState]);

  const emit = useCallback<TypedEmit>(
    (event, ...args) => {
      if (!isConnected) {
        console.warn(`Cannot emit "${String(event)}": socket not connected`);
        return;
      }

      void window.electronApi
        .socketEmit(event as string, ...args)
        .then((result) => {
          if (!result.success) {
            console.warn(
              `Socket emit failed for "${String(event)}":`,
              result.error ?? "unknown_error",
            );
          }
        })
        .catch((error) => {
          console.error(`❌ Socket emit crashed for "${String(event)}":`, error);
        });
    },
    [isConnected],
  );

  const on = useCallback<TypedOn>((event, callback) => {
    const key = event as string;
    const existing = listenersRef.current.get(key) ?? new Set<InternalListener>();
    existing.add(callback as unknown as InternalListener);
    listenersRef.current.set(key, existing);
  }, []);

  const off = useCallback<TypedOff>((event, callback) => {
    const key = event as string;
    const listeners = listenersRef.current.get(key);
    if (!listeners) {
      return;
    }

    if (callback) {
      listeners.delete(callback as unknown as InternalListener);
    } else {
      listeners.clear();
    }

    if (listeners.size === 0) {
      listenersRef.current.delete(key);
    }
  }, []);

  const once = useCallback<TypedOnce>(
    (event, callback) => {
      const wrapped: InternalListener = (...args: unknown[]) => {
        off(event, wrapped as unknown as SocketEvents[typeof event]);
        (callback as unknown as InternalListener)(...args);
      };

      on(event, wrapped as unknown as SocketEvents[typeof event]);
    },
    [off, on],
  );

  const contextValue = useMemo<SocketContextType>(
    () => ({
      socket: socketHandle,
      isConnected,
      emit,
      on,
      off,
      once,
    }),
    [emit, isConnected, off, on, once, socketHandle],
  );

  return (
    <SocketContext.Provider value={contextValue}>
      {children}
    </SocketContext.Provider>
  );
};

export const useSocket = (): SocketContextType => {
  const context = useContext(SocketContext);
  if (context === undefined) {
    throw new Error("useSocket must be used within a SocketProvider");
  }
  return context;
};
