import {
  Loader2, Sparkles, ChevronRight, ChevronDown, Send, Briefcase, Plus,
  Mail, Globe, Search, FileText, FolderOpen, Monitor, Terminal, Camera,
  MapPin, Wand2, Cloud, Battery, Clipboard, RefreshCw, Wrench, Check, X,
  AlertTriangle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppSelector } from "@/store/hooks";
import { useSocket } from "@/context/socketContextProvider";
import type { SparkLogPayload, ApprovalRequestPayload } from "@shared/socket.types";
import EntityCards, { type EntityCardData } from "@/components/local/home/EntityCards";
import DriveFileCards, { type DriveFile } from "@/components/local/home/DriveFileCards";
import WebSearchCards, { type WebSearchData } from "@/components/local/home/WebSearchCards";
import {
  getActiveSessionId, threadStorageKey, startNewSession, updateSession, switchToSession,
} from "@/hooks/useSessionManager";

interface HomeLiveProps {
  entityResult?: { entities: EntityCardData[]; intent: string } | null;
  onEntityDismiss?: () => void;
  showJobs?: boolean;
  onToggleJobs?: () => void;
}

// ─── Storage ────────────────────────────────────────────────────────────────

let currentSessionId = getActiveSessionId();
let STORAGE_KEY = threadStorageKey(currentSessionId);
const COMPAT_KEY = "spark_live_threads";
const MAX_THREADS = 200;
const RENDER_WINDOW = 25;

interface ToolStep {
  tool_name: string;
  task_id: string;
  status: "pending" | "running" | "completed" | "failed";
  latency_ms?: number;
  params_msg?: string;
  steps: string[];
  result_summary?: string;
  scraping_sites?: { url: string; domain: string }[];
}

interface Thread {
  id: string;
  timestamp: string;
  query: string;
  ai_response?: string;
  plan?: string[];
  job_id?: string;
  tools: ToolStep[];
  summary?: string;
  status: "thinking" | "planning" | "executing" | "completed" | "failed";
  entities?: EntityCardData[];
  entityIntent?: string;
  driveFiles?: DriveFile[];
  webSearchData?: WebSearchData;
}

interface QuotaProvider {
  provider: string;
  key_count: number;
  tokens_per_key: number;
  total_tokens: number;
  has_keys: boolean;
  blocked: boolean;
  blocked_since_secs: number;
}
interface QuotaInfo {
  providers: QuotaProvider[];
  total_tokens: number;
  available_tokens: number;
  used_tokens: number;
  pct_used: number;
  configured_providers: number;
}

type ApprovalRequest = ApprovalRequestPayload;

function loadThreads(): Thread[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveThreads(threads: Thread[]) {
  try {
    const data = JSON.stringify(threads.slice(-MAX_THREADS));
    localStorage.setItem(STORAGE_KEY, data);
    // Keep compat key updated so sidebar recent queries always work
    localStorage.setItem(COMPAT_KEY, data);
  } catch { /* quota */ }
}

function timeLabel(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return "now";
  if (diff < 300_000) return `${Math.floor(diff / 60_000)}m`;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ─── Reducer ────────────────────────────────────────────────────────────────
//
// Thread-event correlation rules:
//   - query_received → always creates a new thread; closes stale thinking threads
//   - ai_response → targets the most recent thread WITHOUT an ai_response
//   - plan_created → targets the EARLIEST "thinking" thread without a plan
//   - task_running (new task_id) → targets executing thread whose plan has this tool
//   - subsequent tool events → strict task_id lookup, fallback to executing thread
//
// This prevents events from one query bleeding into another when rapid-fire
// voice commands create multiple threads before the first plan arrives.

function reduceLog(threads: Thread[], log: SparkLogPayload): Thread[] {
  const updated = [...threads];
  const payload = log.payload || {};
  const jobId = (log.job_id || log.payload?.job_id) as string | undefined;
  const taskId = (log.task_id || log.payload?.task_id) as string | undefined;
  const toolName = (log.tool_name || log.payload?.tool_name) as string | undefined;

  // Lookup by taskId and jobId
  const findByTaskIdAndJobId = (taskId: string | undefined, jobId: string | undefined): Thread | undefined => {
    if (!taskId) return undefined;
    if (jobId) {
      for (let i = updated.length - 1; i >= 0; i--) {
        if (updated[i].job_id === jobId && updated[i].tools.some(t => t.task_id === taskId)) return updated[i];
      }
    }
    // Fallback: match by taskId only, but respect jobId isolation
    for (let i = updated.length - 1; i >= 0; i--) {
      const t = updated[i];
      if (jobId && t.job_id && t.job_id !== jobId) continue;
      if (t.tools.some(tool => tool.task_id === taskId)) return t;
    }
    return undefined;
  };

  // Most recent thread in "executing" state, optionally compatible with jobId
  const findExecuting = (jobId?: string): Thread | undefined => {
    for (let i = updated.length - 1; i >= 0; i--) {
      const t = updated[i];
      if (t.status === "executing") {
        if (jobId && t.job_id && t.job_id !== jobId) {
          continue;
        }
        return t;
      }
    }
    return undefined;
  };

  // Lookup by job_id
  const findByJobId = (jobId: string | undefined): Thread | undefined => {
    if (!jobId) return undefined;
    for (let i = updated.length - 1; i >= 0; i--) {
      if (updated[i].job_id === jobId) return updated[i];
    }
    return undefined;
  };

  // Executing thread whose plan includes this tool name, optionally compatible with jobId
  const findExecutingForTool = (toolName: string, jobId?: string): Thread | undefined => {
    if (!toolName) return findExecuting(jobId);
    for (let i = updated.length - 1; i >= 0; i--) {
      const t = updated[i];
      if (t.status === "executing" && t.plan?.includes(toolName)) {
        if (jobId && t.job_id && t.job_id !== jobId) {
          continue;
        }
        return t;
      }
    }
    return findExecuting(jobId);
  };

  // Close conversation-only threads that are old enough to be stale.
  const closeStaleThinking = () => {
    let newestExecutingTs = "";
    for (const t of updated) {
      if ((t.status === "executing" || t.plan?.length) && t.timestamp > newestExecutingTs) {
        newestExecutingTs = t.timestamp;
      }
    }
    for (const t of updated) {
      if (
        t.status === "thinking" &&
        t.ai_response &&
        !t.plan?.length &&
        t.tools.length === 0 &&
        (newestExecutingTs && t.timestamp < newestExecutingTs)
      ) {
        t.status = "completed";
      }
    }
  };

  // Check if all tools in a thread are done
  const checkCompletion = (thread: Thread) => {
    if (thread.tools.length > 0 && thread.tools.every(t => t.status === "completed" || t.status === "failed")) {
      thread.status = thread.tools.some(t => t.status === "failed") ? "failed" : "completed";
    }
  };

  // Resolve thread by checking task_id & job_id, job_id, then transitioning the most recent "thinking" thread
  const resolveThread = (taskId: string | undefined, jobId: string | undefined, toolName?: string): Thread | undefined => {
    // 1. Match by task_id and job_id first
    let thread = findByTaskIdAndJobId(taskId, jobId);
    if (thread) return thread;

    // 2. Match by job_id
    if (jobId) {
      thread = findByJobId(jobId);
      if (thread) return thread;
    }

    // 3. Match the most recent "thinking" or recently completed conversation-only thread
    // (binds the jobId to it and transitions status to executing)
    for (let i = updated.length - 1; i >= 0; i--) {
      const t = updated[i];
      const isThinking = t.status === "thinking";
      const isStaleThinkingClosed = t.status === "completed" && !t.plan?.length && t.tools.length === 0;
      if (isThinking || isStaleThinkingClosed) {
        if (jobId && t.job_id && t.job_id !== jobId) continue;
        thread = t;
        if (jobId) thread.job_id = jobId;
        thread.status = "executing";
        return thread;
      }
    }

    // 4. Match executing thread containing the tool name in its plan
    if (toolName) {
      thread = findExecutingForTool(toolName, jobId);
      if (thread) return thread;
    }

    // 5. Fallback to the most recent executing thread
    return findExecuting(jobId);
  };

  switch (log.event_type) {
    case "query_received": {
      closeStaleThinking();
      updated.push({
        id: `t_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        timestamp: log.timestamp,
        query: payload.query || payload.message || "",
        tools: [],
        status: "thinking",
      });
      break;
    }

    case "ai_response": {
      for (let i = updated.length - 1; i >= 0; i--) {
        if (!updated[i].ai_response) {
          updated[i].ai_response = payload.message || payload.text || "";
          break;
        }
      }
      break;
    }

    case "plan_created": {
      const planTools = payload.tools || (payload.message || "").split(", ").filter(Boolean);
      let matched: Thread | undefined;
      let matchedIdx = -1;

      if (payload.query) {
        const pq = (payload.query as string).trim().toLowerCase();
        for (let i = updated.length - 1; i >= 0; i--) {
          const t = updated[i];
          if (payload.job_id && t.job_id && t.job_id !== payload.job_id) continue;
          const isCandidate = t.status === "thinking" || (t.status === "completed" && !t.plan?.length && t.tools.length === 0);
          if (isCandidate && !t.plan?.length) {
            const tq = t.query.trim().toLowerCase();
            if (tq === pq || pq.startsWith(tq) || tq.startsWith(pq)) {
              matched = t;
              matchedIdx = i;
              break;
            }
          }
        }
      }

      if (!matched) {
        for (let i = updated.length - 1; i >= 0; i--) {
          const t = updated[i];
          if (payload.job_id && t.job_id && t.job_id !== payload.job_id) continue;
          const isCandidate = t.status === "thinking" || (t.status === "completed" && !t.plan?.length && t.tools.length === 0);
          if (isCandidate && !t.plan?.length) {
            matched = t;
            matchedIdx = i;
            break;
          }
        }
      }

      if (matched) {
        matched.plan = planTools;
        matched.status = "executing";
        if (payload.job_id) matched.job_id = payload.job_id as string;
        for (let j = 0; j < matchedIdx; j++) {
          if (updated[j].status === "thinking" && updated[j].ai_response && !updated[j].plan?.length && updated[j].tools.length === 0) {
            updated[j].status = "completed";
          }
        }
      }
      break;
    }

    case "task_running": {
      const thread = resolveThread(taskId, jobId, toolName);
      if (thread) {
        if (jobId && !thread.job_id) {
          thread.job_id = jobId;
        }
        if (thread.status === "thinking") {
          thread.status = "executing";
        }
        const existing = thread.tools.find(t => t.task_id === taskId);
        if (!existing) {
          thread.tools.push({
            tool_name: toolName || "unknown",
            task_id: taskId || "",
            status: "running",
            steps: [],
          });
        } else {
          existing.status = "running";
        }
      }
      break;
    }

    case "tool_params": {
      const thread = resolveThread(taskId, jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === taskId);
        if (tool) tool.params_msg = payload.message || "";
      }
      break;
    }

    case "tool_step":
    case "tool_progress": {
      const thread = resolveThread(taskId, jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === taskId)
          || thread.tools.filter(t => t.status === "running").pop();
        if (tool) {
          if (payload.message && !tool.steps.includes(payload.message)) {
            tool.steps.push(payload.message);
          }
          if (payload.stage === "scraping" && Array.isArray(payload.urls)) {
            tool.scraping_sites = payload.urls;
          }
          if (payload.stage === "scrape_complete" || payload.stage === "extracting") {
            tool.scraping_sites = undefined;
          }
        }
      }
      break;
    }

    case "tool_invoked":
    case "task_completed": {
      const thread = resolveThread(taskId, jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === taskId);
        if (tool) {
          tool.status = (log.status === "success" || log.status === "completed") ? "completed" : "failed";
          tool.latency_ms = payload.latency_ms ?? payload.duration_ms;
          if (payload.result_summary) tool.result_summary = payload.result_summary;
        }
        checkCompletion(thread);
      }
      break;
    }

    case "tool_output": {
      const thread = resolveThread(taskId, jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === taskId)
          || thread.tools.filter(t => t.status === "running").pop();
        if (tool) {
          tool.status = payload.success ? "completed" : "failed";
          tool.latency_ms = payload.duration_ms || tool.latency_ms;
          if (payload.result_summary) tool.result_summary = payload.result_summary;
          if (!payload.success && payload.error) {
            tool.steps.push(payload.error);
          } else if (payload.message && !tool.steps.includes(payload.message) && !payload.result_summary) {
            tool.steps.push(payload.message);
          }
        }
        checkCompletion(thread);
      }
      break;
    }

    case "tool_failed": {
      const thread = resolveThread(taskId, jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const tool = thread.tools.find(t => t.task_id === taskId);
        if (tool) {
          tool.status = "failed";
          tool.steps.push(payload.error || payload.message || "Unknown error");
        }
        checkCompletion(thread);
      }
      break;
    }

    case "execution_complete":
    case "summary": {
      const thread = findByJobId(jobId) || findByTaskIdAndJobId(taskId, jobId) || findExecuting(jobId);
      if (thread) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        for (const tool of thread.tools) {
          if (tool.status === "running" || tool.status === "pending") tool.status = "completed";
        }
        thread.status = thread.tools.some(t => t.status === "failed") ? "failed" : "completed";
        if (payload.message) thread.summary = payload.message;
      }
      break;
    }

    default: {
      const thread = resolveThread(taskId, jobId);
      if (thread && payload.message) {
        if (jobId && !thread.job_id) thread.job_id = jobId;
        const runningTool = thread.tools.filter(t => t.status === "running").pop();
        if (runningTool && !runningTool.steps.includes(payload.message)) {
          runningTool.steps.push(payload.message);
        }
      }
      break;
    }
  }

  return updated.slice(-MAX_THREADS);
}

// ─── Tool label ─────────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  web_research: "Research",
  web_search: "Search",
  web_scrape: "Scrape",
  current_location: "Location",
  file_create: "File",
  file_open: "Open",
  app_open: "App",
  ai_summarize: "Summary",
  shell_execute: "Shell",
  shell_agent: "Shell Agent",
  content_generate: "Generate",
  weather_current: "Weather",
  weather_forecast: "Forecast",
  email_list: "Inbox",
  email_send: "Send Email",
  email_read: "Read Email",
  screenshot_capture: "Screenshot",
  battery_status: "Battery",
  folder_organize: "Organize",
  drive_list: "Drive List",
  drive_search: "File Search",
  drive_read: "Drive Read",
  drive_upload: "Drive Upload",
  drive_move: "Drive Move",
  drive_delete: "Drive Delete",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ─── Tool icon map ───────────────────────────────────────────────────────────

const TOOL_ICON_MAP: Record<string, React.ComponentType<{ size?: number }>> = {
  email_list:         Mail,
  email_send:         Mail,
  email_read:         Mail,
  web_research:       Globe,
  web_search:         Search,
  web_scrape:         Globe,
  file_create:        FileText,
  file_open:          FolderOpen,
  file_read:          FileText,
  app_open:           Monitor,
  shell_execute:      Terminal,
  shell_agent:        Terminal,
  screenshot_capture: Camera,
  current_location:   MapPin,
  drive_list:         FolderOpen,
  drive_search:       Search,
  drive_read:         FileText,
  drive_upload:       FolderOpen,
  drive_move:         FolderOpen,
  drive_delete:       FolderOpen,
  ai_summarize:       Sparkles,
  content_generate:   Wand2,
  weather_current:    Cloud,
  weather_forecast:   Cloud,
  battery_status:     Battery,
  clipboard_read:     Clipboard,
  folder_organize:    FolderOpen,
};

// ─── Tool card ───────────────────────────────────────────────────────────────

function ToolCard({ tool }: { tool: ToolStep }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = tool.status === "running";
  const isFailed  = tool.status === "failed";
  const isDone    = tool.status === "completed";

  const ToolIcon = TOOL_ICON_MAP[tool.tool_name] || Wrench;

  const latencyStr = tool.latency_ms != null
    ? tool.latency_ms < 1000 ? `${tool.latency_ms}ms` : `${(tool.latency_ms / 1000).toFixed(1)}s`
    : null;

  const statusColor = isRunning ? "var(--sp-info)"
    : isDone    ? "var(--sp-ok)"
    : isFailed  ? "var(--sp-err)"
    : "var(--sp-ink-4)";

  const canExpand = !isRunning && (tool.steps.length > 0 || !!tool.result_summary);

  const summaryText = isFailed && tool.steps.length > 0
    ? tool.steps[tool.steps.length - 1]
    : isDone && tool.result_summary ? tool.result_summary
    : isRunning && tool.steps.length > 0 ? tool.steps[tool.steps.length - 1]
    : tool.params_msg || "";

  return (
    <div style={{
      border: `1px solid ${isFailed ? "rgba(201,112,100,0.25)" : "var(--sp-line)"}`,
      borderRadius: 8,
      background: isFailed
        ? "linear-gradient(180deg, rgba(201,112,100,0.04), transparent 60%), var(--sp-bg-2)"
        : "var(--sp-bg-2)",
      overflow: "hidden",
    }}>
      {/* Header row */}
      <button
        onClick={() => { if (canExpand) setExpanded(o => !o); }}
        style={{
          width: "100%",
          display: "flex", alignItems: "center", gap: 11,
          padding: "11px 14px",
          background: "transparent",
          border: 0,
          cursor: canExpand ? "pointer" : "default",
          textAlign: "left",
        }}
      >
        <span style={{ color: "var(--sp-ink-3)", display: "flex", flexShrink: 0 }}>
          <ToolIcon size={15} />
        </span>
        <span className="sp-mono" style={{ fontSize: 13, color: "var(--sp-ink)", fontWeight: 500, flexShrink: 0 }}>
          {toolLabel(tool.tool_name)}
        </span>
        {/* Status dot */}
        <span style={{
          width: 7, height: 7, borderRadius: 99,
          background: statusColor,
          flexShrink: 0,
          boxShadow: isRunning ? `0 0 0 3px ${statusColor}33` : "none",
          transition: "background 200ms",
        }} />
        {latencyStr && (
          <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)", flexShrink: 0 }}>
            {latencyStr}
          </span>
        )}
        {isRunning && !latencyStr && tool.steps.length === 0 && (
          <Loader2 size={11} className="animate-spin" style={{ color: "var(--sp-info)", flexShrink: 0 }} />
        )}
        <span style={{
          flex: 1, minWidth: 0,
          fontSize: 13,
          color: isFailed ? "var(--sp-err)" : "var(--sp-ink-2)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {summaryText}
        </span>
        {canExpand && (
          <span style={{
            color: "var(--sp-ink-4)",
            display: "flex", flexShrink: 0,
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 160ms ease",
          }}>
            <ChevronRight size={14} />
          </span>
        )}
      </button>

      {/* Expanded body */}
      {(expanded || isRunning) && (
        <div style={{
          borderTop: "1px solid var(--sp-line)",
          padding: "10px 14px 12px 40px",
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          {tool.steps.map((step, i) => {
            const isLast = i === tool.steps.length - 1;
            return (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
                <span className="sp-mono" style={{ color: "var(--sp-ink-4)", flexShrink: 0, fontSize: 12 }}>›</span>
                <span className="sp-mono" style={{
                  fontSize: 12, lineHeight: 1.55,
                  color: isRunning && isLast ? "var(--sp-info)" : "var(--sp-ink-3)",
                }}>
                  {step}
                </span>
              </div>
            );
          })}

          {tool.scraping_sites && tool.scraping_sites.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              {tool.scraping_sites.map((site, i) => (
                <span key={i} className="sp-mono" style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  padding: "2px 6px", borderRadius: 4,
                  background: "rgba(0,0,0,0.2)",
                  border: "1px solid var(--sp-line)",
                  fontSize: 10, color: "var(--sp-ink-3)",
                }}>
                  <img
                    src={`https://www.google.com/s2/favicons?domain=${site.domain}&sz=16`}
                    alt=""
                    style={{ width: 12, height: 12, borderRadius: 2 }}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                  {site.domain}
                </span>
              ))}
            </div>
          )}

          {isDone && tool.result_summary && (
            <p className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ok)", lineHeight: 1.5, marginTop: 2 }}>
              {tool.result_summary}
            </p>
          )}

          {isFailed && (
            <button style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              marginTop: 6, padding: "4px 9px",
              borderRadius: 5, border: "1px solid var(--sp-line-2)",
              background: "var(--sp-bg-3)", color: "var(--sp-ink-2)",
              fontSize: 11, cursor: "pointer", width: "fit-content",
            }}>
              <RefreshCw size={10} /> Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Thread view ─────────────────────────────────────────────────────────────

function ThreadView({
  thread, userInitial, onDismissEntities, onDismissDriveFiles, onDismissWebSearch,
}: {
  thread: Thread;
  userInitial: string;
  onDismissEntities?: () => void;
  onDismissDriveFiles?: () => void;
  onDismissWebSearch?: () => void;
}) {
  const hasAssistantContent = !!(
    thread.ai_response ||
    thread.tools.length > 0 ||
    (thread.plan && thread.plan.length > 0) ||
    thread.summary
  );
  const isThinking = thread.status === "thinking" && !thread.ai_response;
  const timeStr = timeLabel(thread.timestamp);

  return (
    <div style={{ padding: "6px 0" }}>
      {/* ── User turn ─────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 14, padding: "10px 0" }}>
        <div style={{ width: 30, flexShrink: 0, display: "flex", justifyContent: "center", paddingTop: 3 }}>
          <div style={{
            width: 26, height: 26, borderRadius: 7,
            background: "linear-gradient(135deg,#3a342a,#2a2620)",
            border: "1px solid var(--sp-line-2)",
            color: "var(--sp-user-tint)",
            fontSize: 12, fontWeight: 600,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "'Geist Mono', ui-monospace, monospace",
          }}>
            {userInitial}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
              You
            </span>
            <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>{timeStr}</span>
          </div>
          <p style={{ marginTop: 5, fontSize: 15, color: "var(--sp-ink)", lineHeight: 1.6 }}>
            {thread.query}
          </p>
        </div>
      </div>

      {/* ── Assistant turn ────────────────────────────────── */}
      {(hasAssistantContent || isThinking) && (
        <div style={{ display: "flex", gap: 14, padding: "4px 0 10px" }}>
          <div style={{ width: 30, flexShrink: 0, display: "flex", justifyContent: "center", paddingTop: 3 }}>
            <div style={{
              width: 26, height: 26, borderRadius: 7,
              background: "linear-gradient(135deg,#d97757,#b54f2c)",
              color: "#fff8f0",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.1), 0 2px 6px rgba(217,119,87,0.2)",
            }}>
              {isThinking
                ? <Loader2 size={13} className="animate-spin" />
                : <Sparkles size={14} strokeWidth={1.6} />
              }
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-accent)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Spark
              </span>
              <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>{timeStr}</span>
              {(() => {
                const hasRunningTools = thread.tools.some(t => t.status === "running" || t.status === "pending");
                const showWorking = (thread.status === "executing" || thread.status === "planning") && hasRunningTools;
                return showWorking ? (
                  <span className="sp-mono" style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    fontSize: 11, padding: "2px 7px", borderRadius: 4,
                    color: "var(--sp-info)",
                    background: "var(--sp-info-soft)",
                    border: "1px solid rgba(135,167,196,0.20)",
                  }}>
                    <Loader2 size={10} className="animate-spin" /> working
                  </span>
                ) : null;
              })()}
            </div>

            {thread.ai_response && (
              <p style={{ marginTop: 6, fontSize: 14, color: "var(--sp-ink-2)", lineHeight: 1.65 }}>
                {thread.ai_response}
              </p>
            )}


            {/* Tool cards */}
            {thread.tools.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
                {thread.tools.map((tool, i) => (
                  <ToolCard key={`${tool.task_id}_${i}`} tool={tool} />
                ))}
              </div>
            )}

            {/* Entity cards */}
            {thread.entities && thread.entities.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <EntityCards
                  entities={thread.entities}
                  intent={thread.entityIntent}
                  onDismiss={() => onDismissEntities?.()}
                />
              </div>
            )}

            {/* Drive file cards */}
            {thread.driveFiles && thread.driveFiles.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <DriveFileCards
                  files={thread.driveFiles}
                  onDismiss={() => onDismissDriveFiles?.()}
                />
              </div>
            )}

            {/* Web search result cards */}
            {thread.webSearchData && thread.webSearchData.results.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <WebSearchCards
                  data={thread.webSearchData}
                  onDismiss={() => onDismissWebSearch?.()}
                />
              </div>
            )}

            {/* Summary — AI verbal response shown after tool execution */}
            {thread.summary && (
              <div style={{
                marginTop: 10,
                padding: "10px 14px",
                borderRadius: 8,
                background: "rgba(217,119,87,0.06)",
                border: "1px solid rgba(217,119,87,0.18)",
              }}>
                <p style={{ margin: 0, fontSize: 13, color: "var(--sp-ink-2)", lineHeight: 1.65 }}>
                  {thread.summary}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Weather-aware greeting ──────────────────────────────────────────────────

interface WeatherCache {
  tempC: number;
  wmoCode: number;
  city: string;
  fetchedAt: number;
}

const WEATHER_KEY = "spark_weather_cache";
const WEATHER_TTL = 30 * 60 * 1000; // 30 min

function loadWeatherCache(): WeatherCache | null {
  try {
    const raw = localStorage.getItem(WEATHER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function buildGreeting(firstName: string, w: WeatherCache | null): { line: string; nameIdx: number } {
  const h = new Date().getHours();
  const time = h >= 5 && h < 12 ? "morning"
    : h >= 12 && h < 14 ? "midday"
    : h >= 14 && h < 18 ? "afternoon"
    : h >= 18 && h < 22 ? "evening" : "night";

  if (!w) {
    const fallbacks: Record<string, string> = {
      morning:   `Early bird, ${firstName} — the morning's all yours.`,
      midday:    `High noon, ${firstName} — keep the momentum going.`,
      afternoon: `Good afternoon, ${firstName} — what's next on the list?`,
      evening:   `Evening, ${firstName} — winding down or just getting started?`,
      night:     `Burning the midnight oil, ${firstName}?`,
    };
    const line = fallbacks[time];
    return { line, nameIdx: line.indexOf(firstName) };
  }

  const { tempC, wmoCode } = w;
  const feel = tempC < 0 ? "freezing" : tempC < 8 ? "cold" : tempC < 15 ? "cool"
    : tempC < 22 ? "mild" : tempC < 28 ? "warm" : "hot";
  const sky = wmoCode === 0 ? "clear" : wmoCode <= 3 ? "cloudy" : wmoCode <= 48 ? "foggy"
    : wmoCode <= 67 ? "rainy" : wmoCode <= 77 ? "snowy" : wmoCode <= 82 ? "showery" : "stormy";

  if (sky === "rainy") {
    const r: Record<string, string> = {
      morning:   `Rainy morning, ${firstName} — the best kind for indoor focus.`,
      midday:    `Midday rain, ${firstName} — stay in, stay sharp.`,
      afternoon: `Rainy afternoon, ${firstName} — perfect excuse to go deep.`,
      evening:   `Rainy evening, ${firstName} — cosy and productive sounds right.`,
      night:     `Raining tonight, ${firstName} — rain and late-night work hit different.`,
    };
    const line = r[time]; return { line, nameIdx: line.indexOf(firstName) };
  }
  if (sky === "snowy") {
    const s: Record<string, string> = {
      morning:   `Snowy morning, ${firstName} — soft and still out there.`,
      midday:    `Snowing midday, ${firstName} — world's on pause, you don't have to be.`,
      afternoon: `Snowy afternoon, ${firstName} — winter magic outside, focus inside.`,
      evening:   `Snowy evening, ${firstName} — lights and snowflakes, let's ship something.`,
      night:     `Snowing tonight, ${firstName} — quiet, cold, and productive.`,
    };
    const line = s[time]; return { line, nameIdx: line.indexOf(firstName) };
  }
  if (sky === "stormy") {
    const line = `Storm out there, ${firstName} — indoors is exactly where you want to be.`;
    return { line, nameIdx: line.indexOf(firstName) };
  }

  const matrix: Record<string, Record<string, string>> = {
    morning: {
      freezing: `Frozen morning, ${firstName} — let's warm things up.`,
      cold:     `Crisp cold morning, ${firstName} — perfect for deep focus.`,
      cool:     `Cool morning air, ${firstName} — good energy today.`,
      mild:     `Gentle morning, ${firstName} — let's make it count.`,
      warm:     `Already warm, ${firstName} — summer energy is here.`,
      hot:      `Scorching start, ${firstName} — work smart, stay cool.`,
    },
    midday: {
      freezing: `Freezing midday, ${firstName} — hope there's somewhere warm.`,
      cold:     `Cold but bright midday, ${firstName} — halfway through.`,
      cool:     `Cool clear midday, ${firstName} — peak focus hours.`,
      mild:     `Mild midday, ${firstName} — energy is just right.`,
      warm:     `Warm midday glow, ${firstName} — let's ride it.`,
      hot:      `Blazing midday, ${firstName} — stay hydrated, stay sharp.`,
    },
    afternoon: {
      freezing: `Bitter afternoon, ${firstName} — warmth is on the other side of this.`,
      cold:     `Cold afternoon, ${firstName} — the kind that sharpens the mind.`,
      cool:     `Cool crisp afternoon, ${firstName} — solid time to push through.`,
      mild:     `Pleasant afternoon, ${firstName} — good time to tackle big things.`,
      warm:     `Warm afternoon, ${firstName} — don't let it slow you down.`,
      hot:      `Hot afternoon, ${firstName} — the grind doesn't stop.`,
    },
    evening: {
      freezing: `Freezing evening, ${firstName} — inside is where it's at.`,
      cold:     `Cold evening, ${firstName} — cosy and productive is the vibe.`,
      cool:     `Cool evening, ${firstName} — great time to reflect and plan.`,
      mild:     `Mild evening, ${firstName} — easy and smooth.`,
      warm:     `Warm golden evening, ${firstName} — let's close the day strong.`,
      hot:      `Warm night ahead, ${firstName} — keep the momentum.`,
    },
    night: {
      freezing: `Frozen night, ${firstName} — the quiet cold hours are yours.`,
      cold:     `Cold and quiet night, ${firstName} — deep work time.`,
      cool:     `Cool night, ${firstName} — the world's asleep, let's build.`,
      mild:     `Still mild out, ${firstName} — night owl mode on.`,
      warm:     `Warm night, ${firstName} — the city doesn't sleep and neither do you.`,
      hot:      `Hot night, ${firstName} — late, warm, and wired in.`,
    },
  };

  const line = matrix[time]?.[feel] ?? `Good ${time}, ${firstName} — what are we getting done?`;
  return { line, nameIdx: line.indexOf(firstName) };
}

// ── Suggestion prompts ───────────────────────────────────────────────────────

const SUGGESTIONS: { label: string; icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }> }[] = [
  { label: "Summarize my unread emails",       icon: Mail      },
  { label: "What's the weather right now?",    icon: Cloud     },
  { label: "Latest news on AI",                icon: Globe     },
  { label: "Organize my Downloads folder",     icon: FolderOpen},
  { label: "Take a screenshot",                icon: Camera    },
  { label: "Write a short professional email", icon: Wand2     },
  { label: "What's my battery level?",         icon: Battery   },
  { label: "Search for Python tutorials",      icon: Search    },
];

// ─── Main component ─────────────────────────────────────────────────────────

export default function HomeLive({ entityResult, onEntityDismiss, showJobs, onToggleJobs }: HomeLiveProps = {}) {
  const { on, off, emit } = useSocket();
  const { user } = useAppSelector((s) => s.auth);
  const [threads, setThreads] = useState<Thread[]>(loadThreads);
  const [inputVal, setInputVal] = useState("");
  const [extraVisible, setExtraVisible] = useState(0);
  const [_sessionId, setSessionId] = useState(currentSessionId);
  const [quotaInfo, setQuotaInfo] = useState<QuotaInfo | null>(null);
  const [quotaOpen, setQuotaOpen] = useState(false);
  const [approvalRequest, setApprovalRequest] = useState<ApprovalRequest | null>(null);
  const [approvalEdits, setApprovalEdits] = useState<Record<string, string>>({});
  const [filePickLoading, setFilePickLoading] = useState(false);
  const [weatherCache, setWeatherCache] = useState<WeatherCache | null>(loadWeatherCache);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const quotaPopoverRef = useRef<HTMLDivElement>(null);
  const threadsRef = useRef(threads);
  threadsRef.current = threads;

  const userInitial = useMemo(() =>
    (user?.fullName?.[0] || user?.username?.[0] || "U").toUpperCase()
  , [user]);
  const userName = user?.fullName || user?.username || "there";

  // Handle spark:log events (primary event stream)
  const handleLog = useCallback((data: SparkLogPayload) => {
    setThreads((prev) => {
      const next = reduceLog(prev, data);
      saveThreads(next);
      return next;
    });
  }, []);

  // Handle job:started events to bind job_id to the query thread early
  const handleJobStarted = useCallback((data: { job_id: string; goal: string }) => {
    setThreads((prev) => {
      const next = [...prev];
      const goal = data.goal.trim().toLowerCase();
      // Look for a candidate thinking thread matching the goal
      for (let i = next.length - 1; i >= 0; i--) {
        const t = next[i];
        if (t.job_id === data.job_id) return prev; // Already bound
        const isCandidate = t.status === "thinking" || (t.status === "completed" && !t.plan?.length && t.tools.length === 0);
        if (isCandidate && !t.job_id) {
          const tq = t.query.trim().toLowerCase();
          if (tq === goal || goal.startsWith(tq) || tq.startsWith(goal)) {
            t.job_id = data.job_id;
            saveThreads(next);
            return next;
          }
        }
      }
      return prev;
    });
  }, []);

  useEffect(() => {
    on("spark:log", handleLog);
    on("job:started", handleJobStarted);
    return () => {
      off("spark:log", handleLog);
      off("job:started", handleJobStarted);
    };
  }, [on, off, handleLog, handleJobStarted]);

  // Fetch quota info once on mount
  useEffect(() => {
    const apiBase = (import.meta as unknown as { env: { VITE_API_BASE_URL?: string } }).env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
    // System routes live at the server root (no /api/v1 prefix)
    const serverRoot = apiBase.replace(/\/api\/v\d+$/, "");
    fetch(`${serverRoot}/quota`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setQuotaInfo(d); })
      .catch(() => {/* server offline */});
  }, []);

  // Fetch weather in background; use cached value for instant greeting on mount
  useEffect(() => {
    const cached = loadWeatherCache();
    if (cached && Date.now() - cached.fetchedAt < WEATHER_TTL) return; // still fresh
    (async () => {
      try {
        const loc = await fetch("https://ipapi.co/json/").then(r => r.json());
        const wx = await fetch(
          `https://api.open-meteo.com/v1/forecast?latitude=${loc.latitude}&longitude=${loc.longitude}&current=temperature_2m,weather_code&timezone=auto`
        ).then(r => r.json());
        const cache: WeatherCache = {
          tempC: wx.current.temperature_2m,
          wmoCode: wx.current.weather_code,
          city: loc.city || "",
          fetchedAt: Date.now(),
        };
        localStorage.setItem(WEATHER_KEY, JSON.stringify(cache));
        setWeatherCache(cache);
      } catch { /* silent — fallback to time-only greeting */ }
    })();
  }, []);

  // Handle approval requests from server (confidential tool confirmation modal)
  useEffect(() => {
    const handleApproval = (data: ApprovalRequest) => {
      if (!data?.task_id) return;
      const inputsCopy = data.inputs ? { ...data.inputs as Record<string, string> } : {};
      setApprovalEdits(inputsCopy);
      setApprovalRequest(data);
    };
    on("task:approval:request", handleApproval);
    return () => { off("task:approval:request", handleApproval); };
  }, [on, off]);

  // Close quota popover when clicking outside
  useEffect(() => {
    if (!quotaOpen) return;
    const handler = (e: MouseEvent) => {
      if (quotaPopoverRef.current && !quotaPopoverRef.current.contains(e.target as Node)) {
        setQuotaOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [quotaOpen]);

  // Handle tool:output for entity cards and rich data (separate socket event with full data)
  useEffect(() => {
    const handler = (data: { success?: boolean; output?: { data?: Record<string, unknown>; tool?: string; task_id?: string; job_id?: string } }) => {
      if (!data?.success || !data?.output?.data) return;
      const output = data.output;
      const toolData = output.data!;
      const toolName = output.tool || "";

      console.log(`📡 [HomeLive] tool:output received — tool=${toolName} task_id=${output.task_id} job_id=${output.job_id}`, Object.keys(toolData));
      if (toolName === "web_research" && toolData.result_type === "entities") {
        console.log(`📡 [HomeLive] 🏨 ENTITY COUNT IN PAYLOAD: ${Array.isArray(toolData.entities) ? (toolData.entities as unknown[]).length : 'NOT_ARRAY'}`, toolData.entities);
      }

      setThreads(prev => {
        const next = [...prev];
        const jobId = output.job_id;

        // ── Entity cards from web_research ──
        if (
          toolName === "web_research" &&
          toolData.result_type === "entities" &&
          Array.isArray(toolData.entities) &&
          (toolData.entities as unknown[]).length > 0
        ) {
          let target: Thread | undefined;
          // Match by task_id and job_id first
          if (output.task_id) {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId && next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
            if (!target) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
          }
          // Match by job_id only if task_id wasn't matched
          if (!target && jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                target = next[i];
                break;
              }
            }
          }
          // Fallback: most recent thread with web_research tool that has no entities yet
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research") && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          // Last resort: most recent thread with web_research in plan
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].plan?.includes("web_research") && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          // Absolute last resort: most recent thread with any tools and no entities
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.length > 0 && !next[i].entities?.length) {
                target = next[i];
                break;
              }
            }
          }
          if (target) {
            const entities = toolData.entities as EntityCardData[];
            console.log(`📡 [HomeLive] 🏨 ATTACHING ${entities.length} entities to thread: "${target.query.slice(0, 40)}" (thread.id=${target.id}, had_entities=${!!target.entities?.length})`);
            target.entities = entities;
            target.entityIntent = (toolData.intent as string) || "results";
            console.log(`📡 [HomeLive] 🏨 AFTER ATTACH: thread.entities.length=${target.entities.length}`);
          } else {
            console.warn("📡 [HomeLive] No matching thread found for entity data — threads:", next.map(t => ({ q: t.query.slice(0, 30), tools: t.tools.map(x => x.tool_name), entities: !!t.entities?.length })));
          }
        }

        // ── Snippets from web_research (factual_lookup / gold price etc.) ──
        if (
          toolName === "web_research" &&
          toolData.result_type === "snippets" &&
          Array.isArray(toolData.snippets) &&
          (toolData.snippets as unknown[]).length > 0
        ) {
          let target: Thread | undefined;
          if (output.task_id) {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId && next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
            if (!target) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
          }
          if (!target && jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                target = next[i];
                break;
              }
            }
          }
          if (!target) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research")) {
                target = next[i];
                break;
              }
            }
          }
          if (target) {
            const tool = target.tools.find((t: ToolStep) => t.task_id === output.task_id)
              || target.tools.find((t: ToolStep) => t.tool_name === "web_research");
            if (tool && !tool.result_summary) {
              const firstSnippet = (toolData.snippets as unknown[])[0];
              tool.result_summary = typeof firstSnippet === "string"
                ? firstSnippet.slice(0, 200)
                : ((firstSnippet as { snippet?: string; text?: string })?.snippet || (firstSnippet as { snippet?: string; text?: string })?.text || "").slice(0, 200);
            }
          }
        }

        // ── Scraped content from web_research (research intent) ──
        if (
          toolName === "web_research" &&
          toolData.result_type === "scraped_content" &&
          (typeof toolData.text === "string" || Array.isArray(toolData.scraped_content))
        ) {
          let target: Thread | undefined;
          if (output.task_id) {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId && next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
            if (!target) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) {
                  target = next[i];
                  break;
                }
              }
            }
          }
          if (!target && jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) { target = next[i]; break; }
            }
          }
          if (target) {
            const tool = target.tools.find((t: ToolStep) => t.task_id === output.task_id)
              || target.tools.find((t: ToolStep) => t.tool_name === "web_research");
            if (tool && !tool.result_summary) {
              const summary = typeof toolData.text === "string" && toolData.text
                ? toolData.text.slice(0, 300)
                : Array.isArray(toolData.scraped_content) && (toolData.scraped_content as { text?: string }[]).length > 0
                  ? ((toolData.scraped_content as { text?: string }[])[0]?.text || "").slice(0, 300)
                  : "";
              if (summary) tool.result_summary = summary;
            }
          }
        }

        // ── Web search results ──
        if (
          toolName === "web_search" &&
          Array.isArray(toolData.results) &&
          (toolData.results as unknown[]).length > 0
        ) {
          let target: Thread | undefined;
          if (jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) { target = next[i]; break; }
            }
          }
          if (!target && output.task_id) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) { target = next[i]; break; }
            }
          }
          if (target) {
            target.webSearchData = {
              query: (toolData.query as string) || "",
              results: toolData.results as WebSearchData["results"],
              total_results: (toolData.total_results as number) || (toolData.results as unknown[]).length,
              search_time_ms: toolData.search_time_ms as number | undefined,
            };
            const tool = target.tools.find((t: ToolStep) => t.task_id === output.task_id)
              || target.tools.find((t: ToolStep) => t.tool_name === "web_search");
            if (tool && !tool.result_summary) {
              tool.result_summary = `${(toolData.results as unknown[]).length} results for "${toolData.query}"`;
            }
          }
        }

        // ── Drive tool results (drive_list, drive_search, drive_upload, etc.) ──
        if (toolName.startsWith("drive_") && output.task_id) {
          const findThread = () => {
            if (jobId) {
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].job_id === jobId) return next[i];
              }
            }
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].tools.some((t: ToolStep) => t.task_id === output.task_id)) return next[i];
            }
            return undefined;
          };
          const target = findThread();
          if (target) {
            // Store rich file list for DriveFileCards rendering
            if (
              (toolName === "drive_list" || toolName === "drive_search") &&
              Array.isArray(toolData.files) &&
              (toolData.files as unknown[]).length > 0
            ) {
              target.driveFiles = toolData.files as DriveFile[];
            }

            const tool = target.tools.find((t: ToolStep) => t.task_id === output.task_id)
              || target.tools.find((t: ToolStep) => t.tool_name === toolName);
            if (tool && !tool.result_summary) {
              if (toolName === "drive_list" || toolName === "drive_search") {
                const files = toolData.files as { name?: string }[] | undefined;
                const total = toolData.total as number | undefined;
                tool.result_summary = files?.length
                  ? `${total ?? files.length} file(s): ${files.slice(0, 5).map((f: { name?: string }) => f.name).join(", ")}${(total ?? 0) > 5 ? "..." : ""}`
                  : "No files found";
              } else if (toolName === "drive_upload") {
                tool.result_summary = `Uploaded "${toolData.name}" to ${toolData.folder || "Drive"}`;
              } else if (toolName === "drive_read") {
                tool.result_summary = `Read ${toolData.name || "file"} (${toolData.size_bytes ? Math.round((toolData.size_bytes as number) / 1024) + "KB" : "unknown size"})`;
              } else if (toolName === "drive_delete") {
                tool.result_summary = `Trashed "${toolData.name}"`;
              } else if (toolName === "drive_move") {
                tool.result_summary = `Moved "${toolData.name}" to ${toolData.destination || "folder"}`;
              }
            }
          }
        }

        // ── Update tool status for any tool output with task_id ──
        if (output.task_id) {
          let matched = false;
          if (jobId) {
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].job_id === jobId) {
                const tool = next[i].tools.find((t: ToolStep) => t.task_id === output.task_id);
                if (tool) {
                  if (tool.status === "running" || tool.status === "pending") {
                    tool.status = "completed";
                  }
                  matched = true;
                  break;
                }
              }
            }
          }
          if (!matched) {
            for (let i = next.length - 1; i >= 0; i--) {
              const tool = next[i].tools.find((t: ToolStep) => t.task_id === output.task_id);
              if (tool) {
                if (tool.status === "running" || tool.status === "pending") {
                  tool.status = "completed";
                }
                break;
              }
            }
          }
        }

        saveThreads(next);
        return next;
      });
    };

    on("tool:output", handler);
    return () => { off("tool:output", handler); };
  }, [on, off]);

  // Fallback: attach entityResult prop to the correct thread
  useEffect(() => {
    if (!entityResult?.entities?.length) return;
    // Capture narrowed values — TS can't carry narrowing into closures
    const entities = entityResult.entities;
    const intent = entityResult.intent;
    console.log(`📡 [HomeLive] 🏨 entityResult PROP received: ${entities.length} entities, intent=${intent}`);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Synchronizing external prop with internal state
    setThreads(prev => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research") && !next[i].entities?.length) {
          console.log(`📡 [HomeLive] 🏨 entityResult PROP: attaching ${entities.length} entities to thread "${next[i].query.slice(0,40)}"`);
          next[i].entities = entities;
          next[i].entityIntent = intent;
          saveThreads(next);
          break;
        } else if (next[i].tools.some((t: ToolStep) => t.tool_name === "web_research")) {
          console.log(`📡 [HomeLive] 🏨 entityResult PROP: skipping thread "${next[i].query.slice(0,40)}" — already has ${next[i].entities?.length} entities`);
        }
      }
      return next;
    });
  }, [entityResult]);

  // Periodically close stale "thinking" threads that are conversation-only.
  // Handles the case where a conversation thread is the LAST one — no future
  // query_received will trigger closeStaleThinking, so it'd spin forever.
  useEffect(() => {
    const interval = setInterval(() => {
      setThreads(prev => {
        const now = Date.now();
        let changed = false;
        const next = prev.map(t => {
          const age = now - new Date(t.timestamp).getTime();
          // Close stale conversation-only "thinking" threads
          if (
            t.status === "thinking" &&
            t.ai_response &&
            !t.plan?.length &&
            t.tools.length === 0 &&
            age > 8000
          ) {
            changed = true;
            return { ...t, status: "completed" as const };
          }
          // Close stuck "executing" threads where all tools already finished
          if (
            (t.status === "executing" || t.status === "planning") &&
            t.tools.length > 0 &&
            t.tools.every(tool => tool.status === "completed" || tool.status === "failed") &&
            age > 10000
          ) {
            changed = true;
            return { ...t, status: (t.tools.some(tool => tool.status === "failed") ? "failed" : "completed") as Thread["status"] };
          }
          // Close "executing" threads with no tools (conversation-only, server never sends completion)
          if (
            (t.status === "executing" || t.status === "planning") &&
            t.tools.length === 0 &&
            t.ai_response &&
            age > 5000
          ) {
            changed = true;
            return { ...t, status: "completed" as const };
          }
          return t;
        });
        if (changed) saveThreads(next);
        return changed ? next : prev;
      });
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [threads]);

  // Only count threads with tools in active state
  const activeCount = threads.filter(t =>
    (t.status === "executing" || t.status === "planning") &&
    (t.plan?.length || t.tools.length)
  ).length;

  const dismissEntities = useCallback((threadId: string) => {
    setThreads(prev => {
      const next = [...prev];
      const t = next.find(x => x.id === threadId);
      if (t) {
        t.entities = undefined;
        t.entityIntent = undefined;
        saveThreads(next);
      }
      return next;
    });
    onEntityDismiss?.();
  }, [onEntityDismiss]);

  const dismissDriveFiles = useCallback((threadId: string) => {
    setThreads(prev => {
      const next = [...prev];
      const t = next.find(x => x.id === threadId);
      if (t) {
        t.driveFiles = undefined;
        saveThreads(next);
      }
      return next;
    });
  }, []);

  const dismissWebSearch = useCallback((threadId: string) => {
    setThreads(prev => {
      const next = [...prev];
      const t = next.find(x => x.id === threadId);
      if (t) {
        t.webSearchData = undefined;
        saveThreads(next);
      }
      return next;
    });
  }, []);

  const saveCurrentMeta = useCallback(() => {
    const t = threadsRef.current;
    if (t.length > 0) {
      updateSession(currentSessionId, {
        threadCount: t.length,
        title: t[0].query.slice(0, 60),
        preview: t[0].query,
      });
    }
  }, []);

  const handleNewSession = useCallback(() => {
    saveCurrentMeta();
    const newId = startNewSession();
    currentSessionId = newId;
    STORAGE_KEY = threadStorageKey(newId);
    setSessionId(newId);
    setThreads([]);
    setExtraVisible(0);
  }, [saveCurrentMeta]);

  // Listen for session switch / new-session events from sidebar
  useEffect(() => {
    const onSwitch = (e: Event) => {
      const sid = (e as CustomEvent).detail.sessionId as string;
      if (sid === currentSessionId) return;
      saveCurrentMeta();
      switchToSession(sid);
      currentSessionId = sid;
      STORAGE_KEY = threadStorageKey(sid);
      setSessionId(sid);
      setThreads(loadThreads());
      setExtraVisible(0);
    };
    const onNew = () => handleNewSession();
    window.addEventListener("spark:switch-session", onSwitch);
    window.addEventListener("spark:new-session", onNew);
    return () => {
      window.removeEventListener("spark:switch-session", onSwitch);
      window.removeEventListener("spark:new-session", onNew);
    };
  }, [saveCurrentMeta, handleNewSession]);

  useEffect(() => {
    if (threads.length === 0 || !threads[0].query) return;
    // First query: set title immediately so sidebar shows it right away
    if (threads.length === 1) {
      updateSession(currentSessionId, {
        threadCount: 1,
        title: threads[0].query.slice(0, 60),
        preview: threads[0].query,
      });
      return;
    }
    // Subsequent updates: debounce to avoid rapid writes
    const timer = setTimeout(() => {
      updateSession(currentSessionId, {
        threadCount: threads.length,
        title: threads[0].query.slice(0, 60),
        preview: threads[0].query,
      });
    }, 2000);
    return () => clearTimeout(timer);
  }, [threads.length]);

  const isEmpty = threads.length === 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;
    emit("send-user-text-query", inputVal.trim());
    setInputVal("");
  };

  const sendApproval = (approved: boolean) => {
    if (!approvalRequest) return;
    const payload: { task_id: string; approved: boolean; edited_inputs?: Record<string, string> } = {
      task_id: approvalRequest.task_id,
      approved,
    };
    if (approved && Object.keys(approvalEdits).length > 0) {
      payload.edited_inputs = approvalEdits;
    }
    emit("task:approval:response", payload);
    setApprovalRequest(null);
    setApprovalEdits({});
    setFilePickLoading(false);
  };

  const inputBox = (
    <div style={{
      border: "1px solid var(--sp-line-2)",
      background: "var(--sp-bg-2)",
      borderRadius: 12,
      padding: "12px 14px",
      display: "flex", flexDirection: "column", gap: 10,
      boxShadow: "0 -1px 0 rgba(255,255,255,0.02), 0 4px 24px rgba(0,0,0,0.28)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Plus size={16} style={{ color: "var(--sp-ink-3)", flexShrink: 0 }} />
        <input
          type="text"
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          placeholder="Ask Spark, or type / for a command…"
          autoFocus={isEmpty}
          style={{
            flex: 1, background: "transparent", border: 0, outline: "none",
            color: "var(--sp-ink)", fontSize: 16,
            fontFamily: "'Geist', -apple-system, BlinkMacSystemFont, sans-serif",
          }}
        />
        <button
          type="submit"
          style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            padding: "7px 12px", borderRadius: 7,
            background: inputVal.trim() ? "var(--sp-accent)" : "var(--sp-bg-3)",
            color: inputVal.trim() ? "#1a1208" : "var(--sp-ink-3)",
            border: inputVal.trim() ? "none" : "1px solid var(--sp-line-2)",
            cursor: inputVal.trim() ? "pointer" : "default",
            transition: "all 140ms",
            flexShrink: 0,
          }}
        >
          <Send size={15} />
        </button>
      </div>
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        {["/inbox", "/research", "/location", "/screenshot", "/shell", "/file"].map(chip => (
          <button
            key={chip}
            type="button"
            onClick={() => setInputVal(chip + " ")}
            className="sp-mono"
            style={{
              display: "inline-flex", alignItems: "center", gap: 2,
              padding: "3px 9px", borderRadius: 5,
              border: "1px solid var(--sp-line)", background: "var(--sp-bg)",
              color: "var(--sp-ink-3)", fontSize: 12, cursor: "pointer",
            }}
          >
            <span style={{ color: "var(--sp-ink-4)" }}>/</span>
            {chip.slice(1)}
          </button>
        ))}
      </div>
    </div>
  );

  const quotaWidget = quotaInfo !== null ? (
    <div ref={quotaPopoverRef} style={{ position: "relative", display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
      {/* Floating popover — appears above the button, aligned to right */}
      {quotaOpen && (
        <div style={{
          position: "absolute",
          bottom: "calc(100% + 6px)",
          right: 0,
          width: 272,
          background: "var(--sp-bg-2)",
          border: "1px solid var(--sp-line-2)",
          borderRadius: 10,
          boxShadow: "0 8px 32px rgba(0,0,0,0.45), 0 2px 8px rgba(0,0,0,0.3)",
          zIndex: 9000,
          overflow: "hidden",
        }}>
          <div style={{ padding: "10px 12px 8px", display: "flex", flexDirection: "column", gap: 8 }}>
            <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Daily quota by provider
            </span>
            {quotaInfo.providers.filter(p => p.has_keys).map(p => {
              const color = p.blocked ? "#c97164" : "var(--sp-accent)";
              return (
                <div key={p.provider} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span className="sp-mono" style={{ fontSize: 11, color: p.blocked ? "var(--sp-err)" : "var(--sp-ink)", fontWeight: 500, display: "flex", alignItems: "center", gap: 5 }}>
                      {p.provider}
                      {p.blocked && <span style={{ fontSize: 9, color: "var(--sp-err)", background: "rgba(201,112,100,0.12)", padding: "1px 5px", borderRadius: 3 }}>blocked</span>}
                    </span>
                    <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>
                      {p.key_count}× · {(p.total_tokens / 1_000).toFixed(0)}k/day
                    </span>
                  </div>
                  <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 99, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: p.blocked ? "100%" : "8%", background: color, borderRadius: 99, transition: "width 400ms ease" }} />
                  </div>
                </div>
              );
            })}
            {quotaInfo.providers.filter(p => !p.has_keys).length > 0 && (
              <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)" }}>
                +{quotaInfo.providers.filter(p => !p.has_keys).length} unconfigured
              </span>
            )}
          </div>
          <div style={{
            padding: "8px 12px",
            borderTop: "1px solid var(--sp-line)",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)" }}>
              Spark · {quotaInfo.pct_used >= 80 ? "Low" : quotaInfo.pct_used >= 50 ? "Medium" : "Free"}
            </span>
            <button
              type="button"
              onClick={() => {
                const apiBase = (import.meta as unknown as { env: { VITE_API_BASE_URL?: string } }).env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
                const serverRoot = apiBase.replace(/\/api\/v\d+$/, "");
                fetch(`${serverRoot}/quota`)
                  .then(r => r.ok ? r.json() : null)
                  .then(d => { if (d) setQuotaInfo(d); })
                  .catch(() => {});
              }}
              style={{ background: "transparent", border: 0, cursor: "pointer", padding: 3, color: "var(--sp-ink-4)", display: "flex" }}
            >
              <RefreshCw size={11} />
            </button>
          </div>
        </div>
      )}

      {/* Circular arc button */}
      <button
        type="button"
        onClick={() => setQuotaOpen(o => !o)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 7,
          background: "transparent", border: 0, cursor: "pointer", padding: "2px 0",
        }}
      >
        {(() => {
          const R = 9, STROKE = 2.5, SIZE = (R + STROKE) * 2;
          const circ = 2 * Math.PI * R;
          const pct = Math.min(quotaInfo.pct_used, 100);
          const dash = circ - (pct / 100) * circ;
          const color = pct >= 80 ? "#c97164" : pct >= 50 ? "#d4a04a" : "var(--sp-accent)";
          return (
            <svg width={SIZE} height={SIZE} style={{ transform: "rotate(-90deg)", flexShrink: 0 }}>
              <circle cx={SIZE/2} cy={SIZE/2} r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={STROKE} />
              <circle
                cx={SIZE/2} cy={SIZE/2} r={R} fill="none"
                stroke={color} strokeWidth={STROKE}
                strokeDasharray={circ}
                strokeDashoffset={dash}
                strokeLinecap="round"
                style={{ transition: "stroke-dashoffset 600ms ease" }}
              />
            </svg>
          );
        })()}
        <span className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-4)" }}>
          {quotaInfo.total_tokens > 0
            ? `${(quotaInfo.available_tokens / 1_000).toFixed(0)}k`
            : "—"}
        </span>
      </button>
    </div>
  ) : null;

  const isEmailTool = approvalRequest?.tool_name === "email_send" || approvalRequest?.tool_name === "gmail_send" || approvalRequest?.tool_name === "email_reply";
  const isDriveTool = approvalRequest?.tool_name?.startsWith("drive_");
  const isUploadTool = approvalRequest?.tool_name === "drive_upload";
  const isCalendarTool = approvalRequest?.tool_name?.startsWith("calendar_");

  const pickLocalFile = async () => {
    if (!window.electronApi?.showOpenFileDialog) return;
    setFilePickLoading(true);
    try {
      const result = await window.electronApi.showOpenFileDialog();
      if (!result.canceled && result.filePaths.length > 0) {
        const fullPath = result.filePaths[0];
        const fileName = fullPath.split(/[\\/]/).pop() || fullPath;
        setApprovalEdits(prev => ({
          ...prev,
          local_path: fullPath,
          // Only auto-fill file_name if not already set by the user
          ...(!prev.file_name && !approvalRequest?.inputs?.file_name ? { file_name: fileName } : {}),
        }));
      }
    } finally {
      setFilePickLoading(false);
    }
  };

  const approvalFields: { key: string; label: string; multiline?: boolean }[] = (() => {
    if (isEmailTool) return [
      { key: "to", label: "To" },
      { key: "subject", label: "Subject" },
      { key: "body", label: "Body", multiline: true },
    ];
    if (isDriveTool) return [
      { key: "file_name", label: "File name" },
      { key: "folder_name", label: "Folder" },
      { key: "destination", label: "Destination" },
      { key: "content", label: "Content", multiline: true },
    ].filter(f =>
      // For drive_upload always show file_name; for others only show present fields
      approvalRequest?.inputs?.[f.key] !== undefined ||
      (approvalRequest?.tool_name === "drive_upload" && f.key === "file_name")
    );
    if (approvalRequest?.tool_name === "calendar_update_event") return [
      { key: "new_summary", label: "New title" },
      { key: "new_start_time", label: "New start" },
      { key: "new_end_time", label: "New end" },
      { key: "new_description", label: "New description", multiline: true },
      { key: "new_location", label: "New location" },
    ].filter(f => approvalRequest?.inputs?.[f.key] !== undefined);
    if (approvalRequest?.tool_name === "calendar_delete_event") return [];
    if (isCalendarTool) return [
      { key: "summary", label: "Event" },
      { key: "start_time", label: "Start" },
      { key: "end_time", label: "End" },
      { key: "description", label: "Description", multiline: true },
    ].filter(f => approvalRequest?.inputs?.[f.key] !== undefined);
    return [];
  })();

  const hasEditableFields = approvalFields.length > 0;
  const hasPlaceholders = (() => {
    if (!approvalRequest?.inputs) return false;
    const re = /\[(Recipient|Your|Insert|Enter|Add)\s[^\]]{2,40}\]/i;
    return Object.values(approvalRequest.inputs).some(v => typeof v === "string" && re.test(v));
  })();

  const modalTitle = (() => {
    if (isEmailTool) return "Review email before sending";
    if (isDriveTool) return "Confirm Drive action";
    if (approvalRequest?.tool_name === "calendar_update_event") return "Confirm event update";
    if (approvalRequest?.tool_name === "calendar_delete_event") return "Confirm event deletion";
    if (isCalendarTool) return "Confirm calendar event";
    return `Confirm: ${approvalRequest?.tool_name?.replace(/_/g, " ") || "action"}`;
  })();

  const approveLabel = (() => {
    if (isEmailTool) return "Send email";
    if (isDriveTool && approvalRequest?.tool_name === "drive_upload") return "Upload";
    if (isDriveTool && approvalRequest?.tool_name === "drive_delete") return "Delete";
    if (approvalRequest?.tool_name === "calendar_update_event") return "Update event";
    if (approvalRequest?.tool_name === "calendar_delete_event") return "Delete event";
    if (isCalendarTool) return "Create event";
    return "Approve";
  })();

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--sp-bg)" }}>

      {/* ── Confidential action approval modal ────────────── */}
      {approvalRequest && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 9999,
          background: "rgba(0,0,0,0.55)",
          display: "flex", alignItems: "center", justifyContent: "center",
          backdropFilter: "blur(4px)",
        }}>
          <div style={{
            width: "100%", maxWidth: 480,
            background: "var(--sp-bg-2)",
            border: "1px solid var(--sp-line-2)",
            borderRadius: 14,
            boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
            overflow: "hidden",
          }}>
            {/* Modal header */}
            <div style={{
              padding: "16px 20px 14px",
              borderBottom: "1px solid var(--sp-line)",
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <AlertTriangle size={16} style={{ color: "var(--sp-warn)", flexShrink: 0 }} />
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--sp-ink)" }}>
                {modalTitle}
              </span>
              <div style={{ flex: 1 }} />
              <button onClick={() => sendApproval(false)} style={{
                background: "transparent", border: 0, cursor: "pointer",
                color: "var(--sp-ink-4)", display: "flex", padding: 4,
              }}>
                <X size={15} />
              </button>
            </div>

            {/* Placeholder warning banner */}
            {hasPlaceholders && (
              <div style={{
                padding: "8px 20px",
                background: "rgba(217,119,87,0.12)",
                borderBottom: "1px solid var(--sp-line)",
                fontSize: 12, color: "var(--sp-warn)",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <AlertTriangle size={12} />
                Content has placeholder text — please review and fill in before sending.
              </div>
            )}

            {/* Modal body */}
            <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12, maxHeight: 400, overflowY: "auto" }}>
              {/* ── Drive upload: file picker ── */}
              {isUploadTool && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <label className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Local file
                  </label>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <div style={{
                      flex: 1, padding: "7px 10px",
                      background: "var(--sp-bg)",
                      border: "1px solid var(--sp-line-2)",
                      borderRadius: 7,
                      fontSize: 12, color: approvalEdits.local_path ? "var(--sp-ink)" : "var(--sp-ink-4)",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {approvalEdits.local_path
                        ? approvalEdits.local_path.split(/[\\/]/).pop()
                        : "No file selected"}
                    </div>
                    <button
                      onClick={pickLocalFile}
                      disabled={filePickLoading}
                      style={{
                        padding: "7px 14px",
                        background: "var(--sp-bg-3)",
                        border: "1px solid var(--sp-line-2)",
                        borderRadius: 7, cursor: filePickLoading ? "default" : "pointer",
                        fontSize: 12, color: "var(--sp-ink-2)",
                        display: "flex", alignItems: "center", gap: 5, flexShrink: 0,
                        opacity: filePickLoading ? 0.6 : 1,
                      }}
                    >
                      <FolderOpen size={13} />
                      {filePickLoading ? "…" : "Browse"}
                    </button>
                  </div>
                  {approvalEdits.local_path && (
                    <span className="sp-mono" style={{ fontSize: 10, color: "var(--sp-ink-4)", wordBreak: "break-all" }}>
                      {approvalEdits.local_path}
                    </span>
                  )}
                </div>
              )}

              {hasEditableFields ? (
                <>
                  {approvalFields.map(({ key: field, label, multiline }) => {
                    const val = approvalEdits[field] ?? (approvalRequest.inputs?.[field] as string ?? "");
                    return (
                      <div key={field} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                        <label className="sp-mono" style={{ fontSize: 11, color: "var(--sp-ink-3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          {label}
                        </label>
                        {multiline ? (
                          <textarea
                            value={val}
                            onChange={e => setApprovalEdits(prev => ({ ...prev, [field]: e.target.value }))}
                            rows={6}
                            style={{
                              background: "var(--sp-bg)",
                              border: "1px solid var(--sp-line-2)",
                              borderRadius: 7, padding: "8px 10px",
                              color: "var(--sp-ink)", fontSize: 13, resize: "vertical",
                              fontFamily: "'Geist', -apple-system, sans-serif",
                            }}
                          />
                        ) : (
                          <input
                            type="text"
                            value={val}
                            onChange={e => setApprovalEdits(prev => ({ ...prev, [field]: e.target.value }))}
                            style={{
                              background: "var(--sp-bg)",
                              border: "1px solid var(--sp-line-2)",
                              borderRadius: 7, padding: "7px 10px",
                              color: "var(--sp-ink)", fontSize: 13, outline: "none",
                            }}
                          />
                        )}
                      </div>
                    );
                  })}
                </>
              ) : (
                <p className="sp-mono" style={{ fontSize: 13, color: "var(--sp-ink-2)", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
                  {approvalRequest.question}
                </p>
              )}
            </div>

            {/* Modal footer */}
            <div style={{
              padding: "12px 20px 16px",
              borderTop: "1px solid var(--sp-line)",
              display: "flex", justifyContent: "flex-end", gap: 8,
            }}>
              <button
                onClick={() => sendApproval(false)}
                style={{
                  padding: "7px 16px", borderRadius: 7,
                  background: "var(--sp-bg-3)",
                  border: "1px solid var(--sp-line-2)",
                  color: "var(--sp-ink-2)", fontSize: 13, cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => sendApproval(true)}
                style={{
                  padding: "7px 16px", borderRadius: 7,
                  background: "var(--sp-accent)",
                  border: "none",
                  color: "#1a1208", fontSize: 13, fontWeight: 600, cursor: "pointer",
                  display: "inline-flex", alignItems: "center", gap: 6,
                }}
              >
                <Check size={13} />
                {approveLabel}
              </button>
            </div>
          </div>
        </div>
      )}

      {isEmpty ? (
        /* ── Empty state ─────────────────────────────────── */
        <div style={{
          flex: 1, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          padding: "0 24px",
          background: "radial-gradient(ellipse at 50% 45%, rgba(217,119,87,0.05) 0%, transparent 65%)",
        }}>
          {/* Dynamic weather-aware greeting */}
          {(() => {
            const firstName = (userName.split(" ")[0]) || "there";
            const { line, nameIdx } = buildGreeting(firstName, weatherCache);
            const before = line.slice(0, nameIdx);
            const after  = line.slice(nameIdx + firstName.length);
            return (
              <p className="sp-serif" style={{
                fontSize: 28, color: "var(--sp-ink)", fontWeight: 400,
                margin: "0 0 8px", textAlign: "center", letterSpacing: "-0.01em",
                lineHeight: 1.3,
              }}>
                {before}
                <span style={{ color: "var(--sp-accent)" }}>{firstName}</span>
                {after}
              </p>
            );
          })()}

          {/* City + temp subtitle if weather loaded */}
          {weatherCache && (
            <p className="sp-mono" style={{
              fontSize: 12, color: "var(--sp-ink-4)",
              margin: "0 0 28px", textAlign: "center",
            }}>
              {weatherCache.city && `${weatherCache.city} · `}{Math.round(weatherCache.tempC)}°C
            </p>
          )}
          {!weatherCache && <div style={{ marginBottom: 28 }} />}

          <div style={{ width: "100%", maxWidth: 600 }}>
            <form onSubmit={handleSubmit}>
              {inputBox}
            </form>
            {quotaWidget}

            {/* Suggestions toggle */}
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
              <button
                type="button"
                onClick={() => setShowSuggestions(o => !o)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  background: "transparent", border: 0, cursor: "pointer",
                  color: "var(--sp-ink-4)", fontSize: 12, padding: "2px 4px",
                  transition: "color 140ms",
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)"; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-4)"; }}
              >
                <Sparkles size={11} />
                <span className="sp-mono">Try a suggestion</span>
                <ChevronDown size={11} style={{
                  transform: showSuggestions ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform 200ms ease",
                }} />
              </button>

              {/* Suggestions grid — smooth reveal */}
              <div style={{
                width: "100%",
                overflow: "hidden",
                maxHeight: showSuggestions ? 300 : 0,
                opacity: showSuggestions ? 1 : 0,
                transition: "max-height 280ms ease, opacity 200ms ease",
              }}>
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                  gap: 7,
                  paddingTop: 4,
                }}>
                  {SUGGESTIONS.map(({ label, icon: Icon }) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => { setInputVal(label); setShowSuggestions(false); }}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "8px 11px", borderRadius: 8, textAlign: "left",
                        background: "var(--sp-bg-2)",
                        border: "1px solid var(--sp-line)",
                        color: "var(--sp-ink-2)", fontSize: 12,
                        cursor: "pointer", transition: "border-color 140ms, background 140ms",
                      }}
                      onMouseEnter={(e) => {
                        const b = e.currentTarget as HTMLButtonElement;
                        b.style.borderColor = "var(--sp-line-2)";
                        b.style.background = "var(--sp-bg-3)";
                      }}
                      onMouseLeave={(e) => {
                        const b = e.currentTarget as HTMLButtonElement;
                        b.style.borderColor = "var(--sp-line)";
                        b.style.background = "var(--sp-bg-2)";
                      }}
                    >
                      <Icon size={13} style={{ color: "var(--sp-accent)", flexShrink: 0 }} />
                      <span style={{ lineHeight: 1.4 }}>{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* ── Session header (compact) ──────────────────── */}
          <div style={{
            padding: "8px 28px 7px",
            borderBottom: "1px solid var(--sp-line)",
            display: "flex", alignItems: "center", gap: 10,
            background: "var(--sp-bg)",
            flexShrink: 0,
          }}>
            <h1 className="sp-serif" style={{ margin: 0, fontSize: 18, color: "var(--sp-ink)", fontWeight: 400, flexShrink: 0 }}>
              Activity
            </h1>
            {threads[0]?.query && (
              <>
                <span style={{ color: "var(--sp-line-2)", flexShrink: 0, fontSize: 16 }}>·</span>
                <span style={{
                  fontSize: 13, color: "var(--sp-ink-4)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  minWidth: 0, maxWidth: 260,
                }}>
                  {threads[0].query.slice(0, 60)}
                </span>
              </>
            )}
            <span style={{
              width: 6, height: 6, borderRadius: 99, flexShrink: 0,
              background: activeCount > 0 ? "var(--sp-warn)" : "var(--sp-ok)",
              boxShadow: `0 0 0 3px ${activeCount > 0 ? "rgba(212,160,74,0.15)" : "var(--sp-ok-soft)"}`,
            }} />
            {activeCount > 0 && (
              <span className="sp-mono" style={{
                fontSize: 10, color: "var(--sp-accent)",
                background: "var(--sp-accent-soft)",
                border: "1px solid rgba(217,119,87,0.18)",
                padding: "1px 7px", borderRadius: 99,
              }}>
                {activeCount} active
              </span>
            )}

            <div style={{ flex: 1 }} />

            <button
              onClick={handleNewSession}
              title="New session"
              style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 26, height: 26, borderRadius: 6,
                background: "transparent",
                border: "1px solid var(--sp-line)",
                color: "var(--sp-ink-3)",
                cursor: "pointer", flexShrink: 0, transition: "all 120ms",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--sp-line-2)";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-2)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--sp-line)";
                (e.currentTarget as HTMLButtonElement).style.color = "var(--sp-ink-3)";
              }}
            >
              <Plus size={13} />
            </button>

            {activeCount > 0 && (
              <button
                onClick={onToggleJobs}
                className="sp-mono"
                style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  padding: "4px 10px", borderRadius: 6,
                  background: showJobs ? "var(--sp-accent-soft)" : "transparent",
                  border: showJobs ? "1px solid rgba(217,119,87,0.25)" : "1px solid var(--sp-line)",
                  color: showJobs ? "var(--sp-accent)" : "var(--sp-ink-3)",
                  fontSize: 11, cursor: "pointer", transition: "all 120ms",
                  flexShrink: 0,
                }}
              >
                <Briefcase size={12} />
                Jobs
                <span style={{
                  background: "var(--sp-accent)", color: "#1a1208",
                  borderRadius: 99, padding: "0 5px", fontSize: 10, fontWeight: 600,
                }}>
                  {activeCount}
                </span>
              </button>
            )}
          </div>

          {/* ── Timeline ─────────────────────────────────── */}
          <div
            className="sp-scroll"
            style={{ flex: 1, overflowY: "auto", padding: "10px 28px 20px", minHeight: 0 }}
          >
            {(() => {
              const windowSize = RENDER_WINDOW + extraVisible;
              const displayed = threads.slice(Math.max(0, threads.length - windowSize));
              const hidden = threads.length - displayed.length;
              return (
                <div style={{ maxWidth: 860, margin: "0 auto" }}>
                  {hidden > 0 && (
                    <div style={{ textAlign: "center", marginBottom: 16 }}>
                      <button
                        onClick={() => setExtraVisible(e => e + 15)}
                        className="sp-mono"
                        style={{
                          fontSize: 11, color: "var(--sp-ink-4)",
                          background: "var(--sp-bg-2)", border: "1px solid var(--sp-line)",
                          borderRadius: 6, padding: "5px 14px", cursor: "pointer",
                        }}
                      >
                        Show {Math.min(15, hidden)} earlier ({hidden} hidden)
                      </button>
                    </div>
                  )}
                  {displayed.map((thread, i) => (
                    <div key={thread.id}>
                      {i > 0 && (
                        <div style={{
                          height: 1,
                          background: "linear-gradient(90deg, transparent, var(--sp-line) 20%, var(--sp-line) 80%, transparent)",
                          margin: "2px 0",
                          opacity: 0.7,
                        }} />
                      )}
                      <ThreadView
                        thread={thread}
                        userInitial={userInitial}
                        onDismissEntities={() => dismissEntities(thread.id)}
                        onDismissDriveFiles={() => dismissDriveFiles(thread.id)}
                        onDismissWebSearch={() => dismissWebSearch(thread.id)}
                      />
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
              );
            })()}
          </div>

          {/* ── Bottom input ──────────────────────────────── */}
          <div style={{
            background: `linear-gradient(180deg, transparent, var(--sp-bg) 30%)`,
            padding: "14px 24px 18px",
            flexShrink: 0,
          }}>
            <div style={{ maxWidth: 860, margin: "0 auto" }}>
              <form onSubmit={handleSubmit}>
                {inputBox}
              </form>
              {quotaWidget}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

