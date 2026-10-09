import type { IBrainStatus } from "@root/types";
import { useAppSelector } from "@/store/hooks";

const COPY: Record<IBrainStatus, { label: string; detail: string; dot: string }> = {
  connected: { label: "Connected", detail: "Spark's brain is connected.", dot: "bg-green-500" },
  connecting: { label: "Connecting…", detail: "Connecting to Spark's brain…", dot: "bg-yellow-400 animate-pulse" },
  offline: { label: "Can't reach the brain", detail: "Can't reach Spark's brain. I'll keep trying.", dot: "bg-red-500" },
  signed_out: { label: "Signed out", detail: "You're signed out.", dot: "bg-neutral-500" },
};

/** Live connection to the brain (R0). `title` carries the longer, human explanation. */
export default function BrainStatus({ className = "" }: { className?: string }) {
  const status = useAppSelector((state) => state.brain.status);
  const copy = COPY[status];
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`} title={copy.detail} role="status" aria-live="polite">
      <span className={`w-1.5 h-1.5 rounded-full ${copy.dot}`} />
      <span>{copy.label}</span>
    </span>
  );
}
