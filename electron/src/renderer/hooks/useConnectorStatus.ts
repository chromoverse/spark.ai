import { useState, useEffect, useCallback } from "react";
import axiosInstance from "@/utils/axiosConfig";

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace("/api/v1", "");

export interface ConnectorStatus {
  id: string;
  display_name: string;
  type: string;
  connected: boolean;
  capabilities: string[];
  description: string;
  icon: string;
  requires_setup: boolean;
}

export function useConnectorStatus(userId: string | undefined) {
  const [connectors, setConnectors] = useState<ConnectorStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await axiosInstance.get(`/connectors/list?user_id=${userId}`, { baseURL: BASE });
      const data = Array.isArray(res) ? res : (res as any)?.data ?? [];
      setConnectors(data);
      setError(null);
    } catch (e: any) {
      setError("Could not reach server");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Auto-refresh every 30s to catch external token revocations
  useEffect(() => {
    if (!userId) return;
    const id = setInterval(fetchAll, 30_000);
    return () => clearInterval(id);
  }, [fetchAll, userId]);

  const pollUntilConnected = useCallback(
    (connectorId: string, signal?: AbortSignal, timeoutMs = 120_000): Promise<boolean> => {
      return new Promise((resolve) => {
        if (signal?.aborted) { resolve(false); return; }

        const deadline = Date.now() + timeoutMs;
        let timerId: ReturnType<typeof setTimeout>;

        const done = (value: boolean) => {
          clearTimeout(timerId);
          resolve(value);
        };

        signal?.addEventListener("abort", () => done(false), { once: true });

        const tick = async () => {
          if (signal?.aborted || Date.now() > deadline) { done(false); return; }
          try {
            const res = await axiosInstance.get(
              `/connectors/${connectorId}/status?user_id=${userId}`,
              { baseURL: BASE }
            );
            const status = (res as any)?.connected ?? (res as any)?.data?.connected ?? false;
            if (status) {
              await fetchAll();
              done(true);
            } else {
              timerId = setTimeout(tick, 2000);
            }
          } catch {
            timerId = setTimeout(tick, 3000);
          }
        };
        timerId = setTimeout(tick, 2000);
      });
    },
    [userId, fetchAll]
  );

  const disconnect = useCallback(
    async (connectorId: string) => {
      if (!userId) return;
      // Optimistic update — card flips immediately, no waiting for server round-trip
      setConnectors((prev) =>
        prev.map((c) => (c.id === connectorId ? { ...c, connected: false } : c))
      );
      try {
        await axiosInstance.delete(`/auth/${connectorId}/disconnect?user_id=${userId}`, { baseURL: BASE });
      } catch (e) {
        await fetchAll(); // revert on failure
        throw e;
      }
      await fetchAll(); // sync server truth
    },
    [userId, fetchAll]
  );

  return { connectors, loading, error, refetch: fetchAll, pollUntilConnected, disconnect };
}
