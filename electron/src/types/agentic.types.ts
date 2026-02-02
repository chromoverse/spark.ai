/* ---------- Literal Types ---------- */

export type ExecutionTarget = "client" | "server";

export type FailurePolicy = "abort" | "continue" | "retry";

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "waiting"
  | "skipped"
  | "emitted";

/* ---------- Lifecycle ---------- */

export interface LifecycleMessages {
  onStart?: string;
  onSuccess?: string;
  onFailure?: string;
}

/* ---------- Task Control ---------- */

export interface TaskControl {
  confidence?: number;
  requiresApproval?: boolean;
  approvalQuestion?: string;
  onFailure: FailurePolicy;
  timeoutMs?: number;
}

/* ---------- Task Definition ---------- */

export interface Task {
  taskId: string;
  tool: string;
  executionTarget: ExecutionTarget;

  dependsOn: string[];

  inputs: Record<string, any>;

  inputBindings: Record<string, string>;

  lifecycleMessages?: LifecycleMessages;
  control?: TaskControl;
}

/* ---------- Task Output ---------- */

export interface TaskOutput {
  success: boolean;
  data: Record<string, any>;
  error?: string;
}

/* ---------- Task Record ---------- */

export interface TaskRecord {
  // Immutable task definition
  task: Task;

  // Execution state
  status: TaskStatus;
  resolvedInputs: Record<string, any>;
  output?: TaskOutput;
  error?: string;

  // Timing (ISO datetime strings)
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;

  // Client tracking
  emittedAt?: string;
  ackReceivedAt?: string;
}
