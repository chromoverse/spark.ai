import { app } from "electron";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import type { IBodyStatus } from "@root/types";

// The spark-body sidecar (docs/API.md §4): spawned once, JSON-RPC 2.0 over stdio, one JSON
// object per line. If it dies, it's restarted with backoff and the windows are told: never silent.

type Params = Record<string, unknown>;
type Notify = (method: string, params: Params) => void;
type StatusListener = (status: IBodyStatus) => void;

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
}

const RESTART_DELAYS_MS = [1_000, 2_000, 5_000, 10_000];

export class BodyError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function bodyDir(): string {
  const candidates = [
    path.resolve(app.getAppPath(), "..", "body"),
    path.resolve(process.cwd(), "..", "body"),
    path.resolve(process.cwd(), "body"),
  ];
  return candidates.find((dir) => fs.existsSync(path.join(dir, "spark_body"))) ?? candidates[0];
}

function pythonPath(dir: string): string {
  if (process.env.SPARK_BODY_PYTHON) return process.env.SPARK_BODY_PYTHON;
  return process.platform === "win32"
    ? path.join(dir, ".venv", "Scripts", "python.exe")
    : path.join(dir, ".venv", "bin", "python");
}

class BodyBridge {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private notifyListeners = new Set<Notify>();
  private statusListeners = new Set<StatusListener>();
  private restarts = 0;
  private stopping = false;
  private status: IBodyStatus = "down";

  getStatus(): IBodyStatus {
    return this.status;
  }

  start(): void {
    if (this.proc) return;
    const dir = bodyDir();
    const python = pythonPath(dir);
    if (!fs.existsSync(python)) {
      console.error(`[body] no Python at ${python}; run \`uv sync\` in body/ or set SPARK_BODY_PYTHON`);
      this.setStatus("missing");
      return;
    }
    this.stopping = false;
    this.setStatus("starting");
    const proc = spawn(python, ["-m", "spark_body"], {
      cwd: dir,
      env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    });
    this.proc = proc;
    readline.createInterface({ input: proc.stdout }).on("line", (line) => this.onLine(line));
    readline.createInterface({ input: proc.stderr }).on("line", (line) => console.log("[body]", line));
    proc.on("exit", (code, signal) => {
      this.proc = null;
      for (const [, p] of this.pending) {
        clearTimeout(p.timer);
        p.reject(new BodyError("body_down", "The voice engine stopped. It's restarting."));
      }
      this.pending.clear();
      this.setStatus("down");
      if (this.stopping) return;
      const delay = RESTART_DELAYS_MS[Math.min(this.restarts, RESTART_DELAYS_MS.length - 1)];
      this.restarts += 1;
      console.warn(`[body] exited (code=${code}, signal=${signal}); restarting in ${delay} ms`);
      setTimeout(() => this.start(), delay);
    });
    proc.on("error", (err) => console.error("[body] spawn failed", err));
  }

  stop(): void {
    this.stopping = true;
    this.proc?.kill();
  }

  call<T = unknown>(method: string, params: Params = {}, timeoutMs = 10_000): Promise<T> {
    const proc = this.proc;
    if (!proc || this.status !== "ready") {
      return Promise.reject(new BodyError("body_down", "The voice engine isn't running right now."));
    }
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new BodyError("timeout", `The voice engine didn't answer ${method} in time.`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject, timer });
      proc.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  onNotify(fn: Notify): () => void {
    this.notifyListeners.add(fn);
    return () => this.notifyListeners.delete(fn);
  }

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  private onLine(line: string): void {
    let msg: { id?: number; method?: string; params?: Params; result?: unknown; error?: { code: number; message: string } };
    try {
      msg = JSON.parse(line) as typeof msg;
    } catch {
      console.warn("[body] non-JSON line on stdout", line.slice(0, 200));
      return;
    }
    if (msg.method) {
      if (msg.method === "body.ready") {
        this.restarts = 0;
        this.setStatus("ready");
      }
      for (const fn of this.notifyListeners) fn(msg.method, msg.params ?? {});
      return;
    }
    const pending = typeof msg.id === "number" ? this.pending.get(msg.id) : undefined;
    if (!pending || msg.id === undefined) return;
    this.pending.delete(msg.id);
    clearTimeout(pending.timer);
    if (msg.error) pending.reject(new BodyError(String(msg.error.code), msg.error.message));
    else pending.resolve(msg.result);
  }

  private setStatus(status: IBodyStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const fn of this.statusListeners) fn(status);
  }
}

export const bodyBridge = new BodyBridge();
