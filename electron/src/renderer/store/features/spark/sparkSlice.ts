import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { IBrainEvent, IBrainJob, IJobStatus, IJobTodo } from "@root/types";

// What the brain pushes (docs/API.md §3.2), folded into what Home shows: the conversation (with
// artifacts inline), live jobs, and the approvals and questions waiting on the user.

export interface Turn {
  kind: "turn";
  key: string;
  signalId: string;
  you: string | null;
  spark: string;
  done: boolean;
  tier: number | null;
  at: number; // ms epoch of its last change (the overlay lingers on it)
}

export interface ArtifactView {
  id: string;
  kind: string;
  name: string;
  preview: { text?: string };
  jobId: string | null;
}

export type Entry =
  Turn | { kind: "artifact"; key: string; artifact: ArtifactView };

export interface JobStep {
  id: string;
  tool: string;
  summary: string;
  status: string;
  deviceId: string | null;
}

export interface JobView {
  id: string;
  title: string;
  status: IJobStatus;
  todo: IJobTodo[];
  etaS: number | null;
  steps: JobStep[];
  note: string | null;
  summary: string | null;
  artifactId: string | null;
}

export interface ApprovalView {
  id: string;
  jobId: string | null;
  tool: string;
  summary: string;
  inputs: Record<string, unknown>;
  risk: string;
  options: string[];
}

export interface AskView {
  id: string;
  jobId: string | null;
  question: string;
  options: string[];
}

export interface NoticeView {
  key: string;
  text: string;
  url: string | null;
  level: string;
}

export interface SparkState {
  entries: Entry[];
  jobs: Record<string, JobView>;
  jobOrder: string[]; // newest first
  approvals: ApprovalView[];
  asks: AskView[];
  notices: NoticeView[];
}

const MAX_ENTRIES = 120;
export const ACTIVE: IJobStatus[] = ["queued", "running", "waiting"];

export const initialSparkState: SparkState = {
  entries: [],
  jobs: {},
  jobOrder: [],
  approvals: [],
  asks: [],
  notices: [],
};

let seq = 0;
const key = (): string => `e${++seq}`;

function trim(state: SparkState): void {
  if (state.entries.length > MAX_ENTRIES)
    state.entries.splice(0, state.entries.length - MAX_ENTRIES);
}

function upsertJob(
  state: SparkState,
  id: string,
  patch: Partial<JobView>,
): JobView {
  const job =
    state.jobs[id] ??
    (state.jobs[id] = {
      id,
      title: "Job",
      status: "queued",
      todo: [],
      etaS: null,
      steps: [],
      note: null,
      summary: null,
      artifactId: null,
    });
  Object.assign(job, patch);
  if (!state.jobOrder.includes(id)) state.jobOrder.unshift(id);
  return job;
}

type D = Record<string, unknown>;
type UserSaid = {
  signalId: string;
  text: string;
  tier: number | null;
  reply?: string;
  done?: boolean;
};
type Stamp = { at: number };
const stamp = (): Stamp => ({ at: Date.now() });
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null =>
  typeof v === "string" ? v : null;

const sparkSlice = createSlice({
  name: "spark",
  initialState: initialSparkState,
  reducers: {
    /** A line the user typed or said (the device already knows its signal id and tier). */
    userSaid: {
      reducer: (state, action: PayloadAction<UserSaid, string, Stamp>) => {
        const { signalId, text, tier, reply, done } = action.payload;
        state.entries.push({
          kind: "turn",
          key: key(),
          signalId,
          you: text,
          spark: reply ?? "",
          done: done ?? false,
          tier,
          at: action.meta.at,
        });
        trim(state);
      },
      prepare: (said: UserSaid) => ({ payload: said, meta: stamp() }),
    },
    jobsLoaded: (state, action: PayloadAction<IBrainJob[]>) => {
      for (const j of [...action.payload].reverse()) {
        upsertJob(state, j.id, {
          title: j.title,
          status: j.status,
          todo: j.todo,
          etaS: j.eta_s,
          summary: j.summary,
        });
      }
    },
    noticeSeen: (state, action: PayloadAction<string>) => {
      state.notices = state.notices.filter((n) => n.key !== action.payload);
    },
    brainEvent: {
      prepare: (e: IBrainEvent) => ({ payload: e, meta: stamp() }),
      reducer: (state, action: PayloadAction<IBrainEvent, string, Stamp>) => {
        const { event } = action.payload;
        const d = (action.payload.data ?? {}) as D;
        switch (event) {
          case "reply.delta": {
            const signalId = str(d.signal_id);
            const text = str(d.text);
            let turn = [...state.entries]
              .reverse()
              .find(
                (e): e is Turn => e.kind === "turn" && e.signalId === signalId,
              );
            // a job speaks again on its origin signal after the turn ended: a new Spark line
            if (!turn || (turn.done && text)) {
              if (!text && d.final) break;
              turn = {
                kind: "turn",
                key: key(),
                signalId,
                you: null,
                spark: "",
                done: false,
                tier: null,
                at: 0,
              };
              state.entries.push(turn);
              trim(state);
              turn = state.entries[state.entries.length - 1] as Turn;
            }
            if (text && d.speak !== false)
              turn.spark = turn.spark ? `${turn.spark} ${text}` : text;
            if (d.final) turn.done = true;
            turn.at = action.meta.at;
            break;
          }
          case "job.update": {
            const id = str(d.job_id);
            if (!id) break;
            const job = upsertJob(state, id, {
              title: str(d.title) || state.jobs[id]?.title || "Job",
              status: (str(d.status) || "running") as IJobStatus,
              todo: Array.isArray(d.todo)
                ? (d.todo as IJobTodo[])
                : (state.jobs[id]?.todo ?? []),
              etaS: typeof d.eta_s === "number" ? d.eta_s : null,
            });
            if (typeof d.note === "string") job.note = d.note;
            if (typeof d.summary === "string") job.summary = d.summary;
            if (typeof d.artifact_id === "string")
              job.artifactId = d.artifact_id;
            const step = d.step as D | undefined;
            if (step && typeof step.id === "string") {
              const view: JobStep = {
                id: step.id,
                tool: str(step.tool),
                summary: str(step.summary),
                status: str(step.status),
                deviceId: strOrNull(step.device_id),
              };
              const i = job.steps.findIndex((s) => s.id === view.id);
              if (i >= 0) job.steps[i] = view;
              else job.steps.push(view);
            }
            if (!ACTIVE.includes(job.status)) {
              state.approvals = state.approvals.filter((a) => a.jobId !== id);
              state.asks = state.asks.filter((a) => a.jobId !== id);
            }
            break;
          }
          case "approval.request":
            state.approvals = state.approvals.filter(
              (a) => a.id !== d.approval_id,
            );
            state.approvals.push({
              id: str(d.approval_id),
              jobId: strOrNull(d.job_id),
              tool: str(d.tool),
              summary: str(d.summary),
              inputs: (d.inputs_preview as Record<string, unknown>) ?? {},
              risk: str(d.risk),
              options: Array.isArray(d.options)
                ? (d.options as string[])
                : ["allow", "deny"],
            });
            break;
          case "approval.resolved":
            state.approvals = state.approvals.filter(
              (a) => a.id !== d.approval_id,
            );
            break;
          case "ask.request":
            state.asks.push({
              id: str(d.ask_id),
              jobId: strOrNull(d.job_id),
              question: str(d.question),
              options: Array.isArray(d.options) ? (d.options as string[]) : [],
            });
            break;
          case "ask.resolved":
            state.asks = state.asks.filter((a) => a.id !== d.ask_id);
            break;
          case "artifact.new":
            state.entries.push({
              kind: "artifact",
              key: key(),
              artifact: {
                id: str(d.artifact_id),
                kind: str(d.kind),
                name: str(d.name),
                preview: (d.preview as { text?: string }) ?? {},
                jobId: strOrNull(d.job_id),
              },
            });
            trim(state);
            break;
          case "notice":
            state.notices.push({
              key: key(),
              text: str(d.text),
              url: strOrNull(d.url),
              level: str(d.level) || "info",
            });
            break;
        }
      },
    },
  },
});

export const { userSaid, jobsLoaded, noticeSeen, brainEvent } =
  sparkSlice.actions;
export default sparkSlice.reducer;

/** The job the panel shows: the newest active one, else the newest. */
export function currentJob(state: SparkState): JobView | null {
  const ids = state.jobOrder;
  const active = ids.find((id) => ACTIVE.includes(state.jobs[id].status));
  return state.jobs[active ?? ids[0]] ?? null;
}
