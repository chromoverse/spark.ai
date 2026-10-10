import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useIsPresent } from "motion/react";
import { ArrowUpRight, Check, Mic, MicOff, Square, X } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { ACTIVE, currentJob, userSaid, type ApprovalView, type AskView, type JobView, type Turn } from "@/store/features/spark/sparkSlice";
import { micLevel, useVoiceEar } from "@/hooks/useVoiceEar";
import { speechLevel } from "@/hooks/useVoicePlayback";
import { ApprovalCard, AskCard } from "@/components/spark/Cards";
import { lingering, overlayLayout, overlayMode, type OverlayLayout } from "./overlayMode";

// The voice overlay (route /ai-panel): Spark's main voice surface, a notch hanging from the top
// edge of the screen. It shows what you said and what Spark says as it happens, the job running,
// and the approvals and questions waiting on you. The ear and the voice live in this window.
// The window itself never moves or resizes (SecondaryWindow): only the notch morphs, in CSS.

const SIZE: Record<OverlayLayout, { w: number; r: number }> = {
  compact: { w: 196, r: 18 },
  live: { w: 340, r: 20 },
  full: { w: 560, r: 28 },
};
const ORB: Record<OverlayLayout, { size: number; left: number; top: number }> = {
  compact: { size: 18, left: 12, top: 9 },
  live: { size: 22, left: 12, top: 9 },
  full: { size: 44, left: 20, top: 20 },
};
const SPRING = { type: "spring", stiffness: 380, damping: 36, mass: 0.9 } as const;
const FADE = { duration: 0.2, ease: [0.2, 0, 0, 1] } as const;

const heardElsewhere = (): void => {};

export default function VoiceOverlay() {
  const spark = useAppSelector((s) => s.spark);
  const brain = useAppSelector((s) => s.brain.status);
  const [speaking, setSpeaking] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [wake, setWake] = useState(true);
  const rootRef = useRef<HTMLDivElement>(null);
  const leaveTimer = useRef<number | null>(null);

  const turn = [...spark.entries].reverse().find((e): e is Turn => e.kind === "turn") ?? null;
  const job = currentJob(spark);
  const activeJob = job && ACTIVE.includes(job.status) ? job : null;

  const ear = useVoiceEar(heardElsewhere, wake); // main sends the line to every window (useBrainBridge)
  const armed = ear.status === "Listening…";
  const turnAt = turn?.at ?? 0;

  const mode = overlayMode({ now, armed, speaking, turn, turnAt, waiting: spark.approvals.length + spark.asks.length, job: activeJob });
  const layout = overlayLayout(mode, hovered, lingering({ now, turn, turnAt }));

  // html/body are transparent here: only the notch is visible
  useEffect(() => {
    document.documentElement.classList.add("sp-overlay-root");
    return () => document.documentElement.classList.remove("sp-overlay-root");
  }, []);

  useEffect(() => {
    const off = window.electronApi.voice.onSpeaking((state) => setSpeaking(state.speaking));
    const load = (): void => {
      void window.electronApi.engines.get().then((r) => {
        if (r.ok) setWake(Boolean(r.data.plan?.wake));
      });
    };
    load();
    const offPlan = window.electronApi.engines.onPlan(load);
    return () => {
      off();
      offPlan();
    };
  }, []);

  // Ctrl+Shift+M and the main window's mic toggle the ear; every window sees its state
  const toggle = ear.toggle;
  useEffect(() => window.electronApi.onMicMuteToggle(() => toggle()), [toggle]);
  useEffect(() => void window.electronApi.voice.earSet(ear.listening), [ear.listening]);

  // re-evaluate timed states (linger, thinking timeout) while one could lapse
  useEffect(() => {
    if (!turn) return;
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [turn]);

  // the orb and the glow follow the voice that's live: Spark's while it talks, else the mic
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    if (!speaking && !ear.listening) {
      el.style.setProperty("--level", "0");
      return;
    }
    let level = 0;
    let raf = 0;
    const tick = (): void => {
      const target = speaking ? speechLevel() : micLevel() * 0.6;
      level += (target - level) * (target > level ? 0.35 : 0.12); // fast attack, slow release
      el.style.setProperty("--level", level.toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speaking, ear.listening]);

  // clicks pass through the transparent window except over the notch
  const enter = (): void => {
    if (leaveTimer.current) window.clearTimeout(leaveTimer.current);
    leaveTimer.current = null;
    void window.electronApi.overlayInteractive(true);
    setHovered(true);
  };
  const leave = (): void => {
    void window.electronApi.overlayInteractive(false);
    leaveTimer.current = window.setTimeout(() => setHovered(false), 350);
  };

  const [height, setHeight] = useState(36);
  const size = SIZE[layout];
  const orb = ORB[layout];

  return (
    <div ref={rootRef} className="sp-sans pointer-events-none fixed inset-x-0 top-0 flex justify-center" data-mode={mode}>
      <motion.div
        className="sp-notch pointer-events-auto relative"
        initial={false}
        animate={{ width: size.w, height, borderBottomLeftRadius: size.r, borderBottomRightRadius: size.r }}
        transition={SPRING}
        onMouseEnter={enter}
        onMouseLeave={leave}
      >
        <span className="sp-notch-flare sp-notch-flare-l" />
        <span className="sp-notch-flare sp-notch-flare-r" />
        <div className="absolute inset-0 overflow-hidden" style={{ borderRadius: "inherit" }}>
          <div className="sp-notch-glow" />
          <div className="sp-notch-edge" />
          <motion.div
            className="sp-orb absolute"
            data-mode={mode}
            initial={false}
            animate={{ width: orb.size, height: orb.size, left: orb.left, top: orb.top }}
            transition={SPRING}
          />
          <AnimatePresence initial={false}>
            <Layer key={layout} width={size.w} onHeight={setHeight}>
              {layout === "compact" && <Compact listening={ear.listening} online={brain === "connected"} />}
              {layout === "live" && activeJob && <Live job={activeJob} />}
              {layout === "full" && (
                <Full
                  mode={mode}
                  turn={turn}
                  job={activeJob}
                  approval={spark.approvals[0] ?? null}
                  more={spark.approvals.length - 1}
                  ask={spark.asks[0] ?? null}
                  hovered={hovered}
                  listening={ear.listening}
                  onToggleMic={ear.toggle}
                  hint={ear.error ?? (brain === "connected" ? ear.status : "Can't reach Spark. Reconnecting…")}
                />
              )}
            </Layer>
          </AnimatePresence>
        </div>
      </motion.div>
    </div>
  );
}

/** One layout's content, cross-fading over the other while the notch morphs. It is laid out at the
 * final width (no reflow mid-morph) and, while present, sets the notch's height. */
function Layer({ width, onHeight, children }: { width: number; onHeight: (h: number) => void; children: React.ReactNode }) {
  const present = useIsPresent();
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || !present) return;
    const report = (): void => onHeight(Math.ceil(node.offsetHeight));
    report();
    const ro = new ResizeObserver(report);
    ro.observe(node);
    return () => ro.disconnect();
  }, [present, onHeight]);
  return (
    <motion.div
      ref={ref}
      className="absolute top-0"
      style={{ width, left: "50%", marginLeft: -width / 2 }}
      initial={{ opacity: 0, filter: "blur(6px)" }}
      animate={{ opacity: 1, filter: "blur(0px)", transition: { ...FADE, delay: 0.06 } }}
      exit={{ opacity: 0, filter: "blur(6px)", transition: { duration: 0.12 } }}
    >
      {children}
    </motion.div>
  );
}

function Compact({ listening, online }: { listening: boolean; online: boolean }) {
  return (
    <div className="flex h-9 items-center pl-10 pr-3.5">
      <span className="text-[12.5px] font-medium tracking-tight text-[var(--sp-ink-2)]">Spark</span>
      <span className="ml-auto flex items-center gap-2">
        {!online && <span className="size-1.5 rounded-full bg-[var(--sp-err)]" title="Can't reach Spark" />}
        {listening ? (
          <Mic className="size-3.5 text-[var(--sp-accent)]" strokeWidth={2.25} />
        ) : (
          <MicOff className="size-3.5 text-[var(--sp-ink-4)]" strokeWidth={2.25} />
        )}
      </span>
    </div>
  );
}

function progress(job: JobView): string | null {
  if (!job.todo.length) return null;
  return `${job.todo.filter((t) => t.status === "done").length}/${job.todo.length}`;
}

function Live({ job }: { job: JobView }) {
  const p = progress(job);
  return (
    <div className="flex h-10 items-center gap-3 pl-12 pr-4">
      <span className="truncate text-[12.5px] font-medium text-[var(--sp-ink)]">{job.title}</span>
      {p && <span className="sp-mono ml-auto shrink-0 text-[11px] text-[var(--sp-ink-3)]">{p}</span>}
    </div>
  );
}

interface FullProps {
  mode: ReturnType<typeof overlayMode>;
  turn: Turn | null;
  job: JobView | null;
  approval: ApprovalView | null;
  more: number;
  ask: AskView | null;
  hovered: boolean;
  listening: boolean;
  onToggleMic: () => void;
  hint: string | null;
}

function Full({ mode, turn, job, approval, more, ask, hovered, listening, onToggleMic, hint }: FullProps) {
  return (
    <div className="flex flex-col gap-3 pb-4 pl-[84px] pr-5 pt-[22px]">
      <Exchange mode={mode} turn={turn} listening={listening} />
      {job && <JobRow job={job} />}
      {approval && <ApprovalCard approval={approval} more={more} />}
      {ask && <AskCard ask={ask} />}
      {hovered && <Controls listening={listening} onToggleMic={onToggleMic} speaking={mode === "speaking"} hint={hint} />}
    </div>
  );
}

function Exchange({ mode, turn, listening }: { mode: FullProps["mode"]; turn: Turn | null; listening: boolean }) {
  if (mode === "listening") {
    return (
      <div className="flex min-h-[44px] items-center gap-3">
        <span className="text-[15px] text-[var(--sp-ink)]">Listening…</span>
        <span className="sp-wave" aria-hidden>
          <i />
          <i />
          <i />
          <i />
          <i />
        </span>
      </div>
    );
  }
  if (!turn) {
    return (
      <div className="flex min-h-[44px] items-center text-[14px] text-[var(--sp-ink-3)]">
        {listening ? "Say “Hey Spark”, or type below." : "The mic is off. Turn it on, or type below."}
      </div>
    );
  }
  return (
    <div className="flex min-h-[44px] flex-col justify-center gap-1">
      {turn.you && <p className="line-clamp-2 text-[13px] leading-snug text-[var(--sp-ink-3)]">{turn.you}</p>}
      {turn.spark ? (
        <p className="sp-scroll max-h-[132px] overflow-y-auto text-[15.5px] leading-[1.45] text-[var(--sp-ink)]">{turn.spark}</p>
      ) : mode === "thinking" ? (
        <p className="sp-shimmer text-[15.5px] leading-[1.45]">Thinking…</p>
      ) : turn.done ? (
        <p className="flex items-center gap-1.5 text-[14px] text-[var(--sp-ink-2)]">
          <Check className="size-4 text-[var(--sp-ok)]" /> Done
        </p>
      ) : null}
    </div>
  );
}

function JobRow({ job }: { job: JobView }) {
  const step = job.steps[job.steps.length - 1];
  const p = progress(job);
  return (
    <div className="flex items-center gap-3 rounded-xl bg-white/[0.04] px-3 py-2.5">
      <span className="sp-spinner" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-[var(--sp-ink)]">{job.title}</p>
        <p className="truncate text-[12px] text-[var(--sp-ink-3)]">
          {job.status === "waiting" ? "Waiting on you" : (job.note ?? step?.summary ?? "Working…")}
        </p>
      </div>
      {p && <span className="sp-mono text-[11px] text-[var(--sp-ink-3)]">{p}</span>}
      <button
        className="sp-btn-ghost"
        onClick={() => void window.electronApi.brain.cancelJob(job.id)}
        title="Stop this job"
      >
        <Square className="size-3 fill-current" />
      </button>
    </div>
  );
}

function Controls({ listening, onToggleMic, speaking, hint }: { listening: boolean; onToggleMic: () => void; speaking: boolean; hint: string | null }) {
  const dispatch = useAppDispatch();
  const [text, setText] = useState("");
  const send = async (): Promise<void> => {
    const said = text.trim();
    if (!said) return;
    setText("");
    const r = await window.electronApi.voice.send(said); // a sent line reaches every window
    if (!r.ok) dispatch(userSaid({ signalId: `local-${Date.now()}`, text: said, tier: null, reply: r.error.message, done: true }));
  };
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <button
          className={listening ? "sp-btn-accent-soft" : "sp-btn-ghost"}
          onClick={onToggleMic}
          title={listening ? "Turn the mic off (Ctrl+Shift+M)" : "Turn the mic on (Ctrl+Shift+M)"}
        >
          {listening ? <Mic className="size-4" /> : <MicOff className="size-4" />}
        </button>
        <form
          className="flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <input className="sp-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type to Spark…" maxLength={2000} />
        </form>
        {speaking ? (
          <button className="sp-btn-ghost" onClick={() => void window.electronApi.voice.stop()} title="Stop talking">
            <X className="size-4" />
          </button>
        ) : (
          <button className="sp-btn-ghost" onClick={() => void window.electronApi.openMainWindow()} title="Open Spark">
            <ArrowUpRight className="size-4" />
          </button>
        )}
      </div>
      {hint && hint !== "Listening…" && <p className="truncate pl-1 text-[11.5px] text-[var(--sp-ink-4)]">{hint}</p>}
    </div>
  );
}
