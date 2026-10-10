import type { JobView, Turn } from "@/store/features/spark/sparkSlice";

// What the voice overlay shows, from what's going on. Pure, so it's tested without a window.

export type OverlayMode = "idle" | "working" | "thinking" | "listening" | "speaking" | "attention";
export type OverlayLayout = "compact" | "live" | "full";

export const LINGER_MS = 7_000; // a finished exchange stays readable this long
const THINKING_MS = 30_000; // a turn the brain never finished stops "thinking" after this

export interface OverlayInputs {
  now: number;
  armed: boolean; // a bare "Hey Spark" was heard: the command is coming
  speaking: boolean;
  turn: Turn | null; // the latest exchange
  turnAt: number; // when it last changed
  waiting: number; // approvals + questions open
  job: JobView | null; // the active job, if any
}

export function overlayMode(s: OverlayInputs): OverlayMode {
  if (s.waiting > 0) return "attention";
  if (s.speaking) return "speaking";
  if (s.armed) return "listening";
  if (s.turn && !s.turn.done && !s.turn.spark && s.now - s.turnAt < THINKING_MS) return "thinking";
  if (s.job) return "working";
  return "idle";
}

/** compact: the resting notch. live: a job's progress, still small. full: the conversation. */
export function overlayLayout(mode: OverlayMode, hovered: boolean, lingering: boolean): OverlayLayout {
  if (hovered || lingering || mode === "attention" || mode === "speaking" || mode === "listening" || mode === "thinking") {
    return "full";
  }
  return mode === "working" ? "live" : "compact";
}

export function lingering(s: Pick<OverlayInputs, "now" | "turn" | "turnAt">): boolean {
  return s.turn !== null && s.now - s.turnAt < LINGER_MS;
}
