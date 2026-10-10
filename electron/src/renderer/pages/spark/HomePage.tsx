import { useEffect, useRef, useState } from "react";
import { ArrowUp, Check, Copy, Mic, MicOff, Square, X } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { ACTIVE, currentJob, userSaid, type ArtifactView, type JobView, type Turn } from "@/store/features/spark/sparkSlice";
import { ApprovalCard, AskCard } from "@/components/spark/Cards";
import BrainStatus from "@/components/spark/BrainStatus";
import { useEar } from "@/hooks/useEar";
import { fmtEta } from "./logic";
import { Dot, Page } from "./ui";

// Home (DESIGN.md §3): the conversation, the approvals and questions waiting on you, and the live
// job panel. The same conversation shows in the voice overlay; each window folds the same events.

export default function HomePage() {
  const spark = useAppSelector((s) => s.spark);
  const job = currentJob(spark);
  return (
    <Page title="Home" actions={<BrainStatus className="text-[12px] text-[var(--sp-ink-3)]" />}>
      <div className="flex h-full min-h-0">
        <Conversation />
        <JobPanel job={job} recent={spark.jobOrder.map((id) => spark.jobs[id]).filter((j) => !ACTIVE.includes(j.status)).slice(0, 6)} />
      </div>
    </Page>
  );
}

function Conversation() {
  const { entries, approvals, asks } = useAppSelector((s) => s.spark);
  const [speaking, setSpeaking] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => window.electronApi.voice.onSpeaking((s) => setSpeaking(s.speaking)), []);
  const last = entries[entries.length - 1];
  const tail = last ? (last.kind === "turn" ? `${last.key}:${last.spark.length}` : last.key) : "";
  // braces: scrollIntoView returns a Promise in new Chromium, and an effect may only return a cleanup
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [tail, approvals.length, asks.length]);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="sp-scroll min-h-0 flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto flex max-w-[720px] flex-col gap-4">
          {entries.length === 0 && (
            <div className="py-24 text-center">
              <p className="text-[15px] text-[var(--sp-ink-2)]">Say “Hey Spark”, or type below.</p>
              <p className="mt-1 text-[13px] text-[var(--sp-ink-4)]">Try “what's in my downloads” or “make a shopping list on my desktop”.</p>
            </div>
          )}
          {entries.map((e) =>
            e.kind === "turn" ? (
              <TurnView key={e.key} turn={e} speaking={speaking && e === last} />
            ) : (
              <Artifact key={e.key} artifact={e.artifact} />
            ),
          )}
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} full />
          ))}
          {asks.map((a) => (
            <AskCard key={a.id} ask={a} />
          ))}
          <div ref={end} />
        </div>
      </div>
      <InputBar />
    </div>
  );
}

function TurnView({ turn, speaking }: { turn: Turn; speaking: boolean }) {
  return (
    <>
      {turn.you && (
        <div className="self-end max-w-[80%] rounded-2xl rounded-br-md bg-[var(--sp-bg-3)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--sp-user-tint)]">
          {turn.you}
        </div>
      )}
      {turn.spark ? (
        <p className="max-w-[90%] text-[14.5px] leading-relaxed text-[var(--sp-ink)]">
          {turn.spark}
          {speaking && (
            <span className="sp-wave ml-2 align-middle" aria-label="Spark is speaking" style={{ height: 14 }}>
              <i />
              <i />
              <i />
            </span>
          )}
        </p>
      ) : !turn.done ? (
        <p className="sp-shimmer text-[14.5px]">Thinking…</p>
      ) : turn.tier === 0 ? (
        <p className="flex items-center gap-1.5 text-[13px] text-[var(--sp-ink-3)]">
          <Check className="size-3.5 text-[var(--sp-ok)]" /> Done
        </p>
      ) : null}
    </>
  );
}

function Artifact({ artifact }: { artifact: ArtifactView }) {
  const text = artifact.preview.text ?? "";
  return (
    <div className="sp-box overflow-hidden">
      <div className="flex items-center gap-2 border-b border-[var(--sp-line)] px-4 py-2 text-[12.5px] text-[var(--sp-ink-2)]">
        <span className="truncate">{artifact.name}</span>
        <span className="flex-1" />
        {text && (
          <button className="sp-btn-ghost h-7 px-2.5 text-[12px]" onClick={() => void navigator.clipboard.writeText(text)}>
            <Copy className="size-3.5" /> Copy
          </button>
        )}
      </div>
      {text && <p className="whitespace-pre-wrap px-4 py-3 text-[13.5px] leading-relaxed text-[var(--sp-ink-2)]">{text}</p>}
    </div>
  );
}

function InputBar() {
  const dispatch = useAppDispatch();
  const ear = useEar();
  const [text, setText] = useState("");
  const send = async (): Promise<void> => {
    const said = text.trim();
    if (!said) return;
    setText("");
    const r = await window.electronApi.voice.send(said); // the line reaches every window
    if (!r.ok) dispatch(userSaid({ signalId: `local-${Date.now()}`, text: said, tier: null, reply: r.error.message, done: true }));
  };
  return (
    <form
      className="mx-auto mb-5 flex w-full max-w-[760px] items-center gap-2 px-8"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <div className="flex flex-1 items-center gap-2 rounded-2xl border border-[var(--sp-line-2)] bg-[var(--sp-bg-2)] py-1.5 pl-4 pr-1.5 focus-within:border-[rgba(249,115,22,0.45)]">
        <input
          className="h-9 flex-1 bg-transparent text-[14px] text-[var(--sp-ink)] outline-none placeholder:text-[var(--sp-ink-4)]"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type to Spark, or say “Hey Spark”…"
          maxLength={2000}
          aria-label="Message Spark"
        />
        <button
          type="button"
          className={ear.listening ? "sp-btn-accent-soft size-9 rounded-xl" : "sp-btn-ghost size-9 rounded-xl"}
          onClick={ear.toggle}
          title={ear.listening ? "Turn the mic off (Ctrl+Shift+M)" : "Turn the mic on (Ctrl+Shift+M)"}
          aria-pressed={ear.listening}
        >
          {ear.listening ? <Mic className="size-4" /> : <MicOff className="size-4" />}
        </button>
        <button type="submit" className="sp-btn-accent size-9 rounded-xl" disabled={!text.trim()} aria-label="Send">
          <ArrowUp className="size-4" />
        </button>
      </div>
    </form>
  );
}

const TONE: Record<string, "ok" | "warn" | "err" | "info" | "off"> = {
  queued: "info",
  running: "info",
  waiting: "warn",
  done: "ok",
  failed: "err",
  cancelled: "off",
};

export function JobPanel({ job, recent }: { job: JobView | null; recent: JobView[] }) {
  const live = job && ACTIVE.includes(job.status) ? job : null;
  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-l border-[var(--sp-line)] bg-[var(--sp-bg-2)]" aria-live="polite">
      {live ? (
        <>
          <header className="border-b border-[var(--sp-line)] px-4 py-3.5">
            <div className="flex items-center gap-2">
              <Dot tone={TONE[live.status]} />
              <h3 className="truncate text-[13.5px] font-medium text-[var(--sp-ink)]">{live.title}</h3>
              {live.status === "waiting" && <span className="sp-tag sp-tag-waiting ml-auto">needs you</span>}
            </div>
            {live.etaS !== null && <p className="mt-1 text-[12px] text-[var(--sp-ink-4)]">About {fmtEta(live.etaS)} left</p>}
          </header>
          <div className="sp-scroll min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {live.todo.length > 0 && (
              <section className="mb-4">
                <h5 className="mb-2 text-[11px] uppercase tracking-[0.08em] text-[var(--sp-ink-4)]">Checklist</h5>
                {live.todo.map((t, i) => (
                  <div key={i} className="flex items-start gap-2 py-1 text-[12.5px]">
                    <span
                      className={`mt-0.5 flex size-3.5 shrink-0 items-center justify-center rounded border ${t.status === "done" ? "border-[var(--sp-ok)] bg-[var(--sp-ok-soft)] text-[var(--sp-ok)]" : t.status === "in_progress" ? "border-[var(--sp-accent)]" : "border-[var(--sp-line-2)]"}`}
                    >
                      {t.status === "done" && <Check className="size-2.5" />}
                    </span>
                    <span className={t.status === "done" ? "text-[var(--sp-ink-4)] line-through" : t.status === "in_progress" ? "text-[var(--sp-ink)]" : "text-[var(--sp-ink-3)]"}>{t.text}</span>
                  </div>
                ))}
              </section>
            )}
            <section>
              <h5 className="mb-2 text-[11px] uppercase tracking-[0.08em] text-[var(--sp-ink-4)]">Steps</h5>
              {live.steps.length === 0 && <p className="text-[12.5px] text-[var(--sp-ink-4)]">Getting started…</p>}
              {live.steps.map((s) => (
                <div key={s.id} className="flex items-start gap-2 py-1.5">
                  <StepIcon status={s.status} />
                  <div className="min-w-0">
                    <p className="sp-mono truncate text-[11.5px] text-[var(--sp-ink-2)]">{s.tool.replaceAll("_", " ")}</p>
                    <p className="truncate text-[12px] text-[var(--sp-ink-4)]">{s.summary}</p>
                  </div>
                </div>
              ))}
              {live.note && <p className="mt-2 rounded-lg bg-white/[0.03] px-3 py-2 text-[12px] italic text-[var(--sp-ink-3)]">“{live.note}”</p>}
            </section>
          </div>
          <div className="border-t border-[var(--sp-line)] p-3">
            <button className="sp-btn-ghost w-full text-[var(--sp-err)]" onClick={() => void window.electronApi.brain.cancelJob(live.id)}>
              <Square className="size-3 fill-current" /> Stop
            </button>
          </div>
        </>
      ) : (
        <>
          <header className="border-b border-[var(--sp-line)] px-4 py-3.5">
            <h3 className="text-[13.5px] font-medium text-[var(--sp-ink)]">Jobs</h3>
            <p className="mt-1 text-[12px] text-[var(--sp-ink-4)]">Nothing running</p>
          </header>
          <div className="sp-scroll min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {recent.length === 0 ? (
              <p className="text-[12.5px] leading-relaxed text-[var(--sp-ink-4)]">Multi-step tasks show up here with a checklist and a Stop button.</p>
            ) : (
              recent.map((j) => (
                <div key={j.id} className="flex items-start gap-2 py-1.5">
                  <StepIcon status={j.status === "done" ? "ok" : j.status === "failed" ? "error" : "denied"} />
                  <div className="min-w-0">
                    <p className="truncate text-[12.5px] text-[var(--sp-ink-2)]">{j.title}</p>
                    {j.summary && <p className="truncate text-[12px] text-[var(--sp-ink-4)]">{j.summary}</p>}
                  </div>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function StepIcon({ status }: { status: string }) {
  if (status === "running") return <span className="sp-spinner mt-0.5 !size-3.5" />;
  const ok = status === "ok";
  const bad = status === "error";
  return (
    <span
      className={`mt-0.5 flex size-3.5 shrink-0 items-center justify-center rounded-full ${ok ? "bg-[var(--sp-ok-soft)] text-[var(--sp-ok)]" : bad ? "bg-[var(--sp-err-soft)] text-[var(--sp-err)]" : "bg-white/5 text-[var(--sp-ink-4)]"}`}
    >
      {ok ? <Check className="size-2.5" /> : <X className="size-2.5" />}
    </span>
  );
}
