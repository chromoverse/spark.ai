import type { IBrainJob, IBrainResult } from "@root/types";
import { ipcMainHandle } from "../utils/ipcUtils.js";
import { BrainError, brainAuth } from "../services/BrainAuth.js";
import { brainSocket } from "../services/BrainSocket.js";

const BAD_INPUT = "That doesn't look quite right. Check it and try again.";

async function result<T>(fn: () => Promise<T>): Promise<IBrainResult<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (err) {
    if (err instanceof BrainError) return { ok: false, error: { code: err.code, message: err.message } };
    console.error("[brain] ipc failed", err);
    return { ok: false, error: { code: "internal", message: "Something went sideways. Try again in a moment." } };
  }
}

function field(payload: unknown, key: string, pattern: RegExp): string {
  const value = (payload as Record<string, unknown> | null)?.[key];
  if (typeof value !== "string" || !pattern.test(value.trim())) {
    throw new BrainError("invalid_input", BAD_INPUT);
  }
  return value.trim();
}

const EMAIL = /^[^\s@]{1,64}@[^\s@]+\.[^\s@]{2,}$/;

export function registerBrainHandlers(): void {
  ipcMainHandle("brainOtpStart", (_event, payload) =>
    result(async () => {
      await brainAuth.startOtp(field(payload, "email", EMAIL));
      return { sent: true };
    }),
  );

  ipcMainHandle("brainOtpVerify", (_event, payload) =>
    result(() => brainAuth.verifyOtp(field(payload, "email", EMAIL), field(payload, "code", /^\d{6}$/))),
  );

  ipcMainHandle("brainGoogleSignIn", () => result(() => brainAuth.signInWithGoogle()));

  ipcMainHandle("brainGetSession", () =>
    result(async () => ((await brainAuth.hasSession()) ? brainAuth.session() : null)),
  );

  ipcMainHandle("brainSignOut", () =>
    result(async () => {
      brainSocket.disconnect("signed_out");
      await brainAuth.signOut();
      return { signedOut: true };
    }),
  );

  ipcMainHandle("brainGetStatus", () => brainSocket.getStatus());

  // Jobs (R2): approvals and questions go back over the socket; the first answer from any device
  // wins. Job state for the panel comes from job.update events and, after a reconnect, /v2/jobs.
  const ID = /^[\w-]{1,64}$/;
  ipcMainHandle("brainApprove", (_event, payload) =>
    result(async () => {
      const decision = field(payload, "decision", /^(allow|deny|always)$/);
      const ack = await brainSocket.emit("approval.response", {
        approval_id: field(payload, "approvalId", ID),
        decision,
      });
      return { accepted: Boolean((ack?.data as { accepted?: boolean } | undefined)?.accepted) };
    }),
  );
  ipcMainHandle("brainAnswer", (_event, payload) =>
    result(async () => {
      const ack = await brainSocket.emit("ask.response", {
        ask_id: field(payload, "askId", ID),
        answer: field(payload, "answer", /^[\s\S]{1,500}$/),
      });
      return { accepted: Boolean((ack?.data as { accepted?: boolean } | undefined)?.accepted) };
    }),
  );
  ipcMainHandle("brainJobCancel", (_event, payload) =>
    result(() => brainAuth.request<{ status: string }>("POST", `/v2/jobs/${field(payload, "jobId", ID)}/cancel`)),
  );
  ipcMainHandle("brainJobs", () => result(() => brainAuth.request<{ items: IBrainJob[] }>("GET", "/v2/jobs?limit=30")));
}
