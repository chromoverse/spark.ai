import type { IBrainResult } from "@root/types";
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
}
