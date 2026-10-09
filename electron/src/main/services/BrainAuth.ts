import { app, shell } from "electron";
import keytar from "keytar";
import crypto from "node:crypto";
import http from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import type { IBrainSession, IBrainUser } from "@root/types";

// Brain v2 auth (docs/API.md §2.1). Tokens never reach the renderer: the refresh token lives in
// the OS keychain, the 15-minute access token only in this process's memory.

export const BRAIN_URL = (process.env.VITE_BRAIN_URL ?? "http://127.0.0.1:8080").replace(/\/$/, "");

const KEYCHAIN_SERVICE = "SparkAI";
const REFRESH_ACCOUNT = "brain-refresh-token";
const DEVICE_ACCOUNT = "brain-device-id";
const HTTP_TIMEOUT_MS = 10_000;
const GOOGLE_TIMEOUT_MS = 5 * 60_000;

const UNREACHABLE = "Can't reach Spark's brain right now. Is it running?";
const SIGNED_OUT = "You've been signed out. Sign in again and we're good.";

export class BrainError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

interface Envelope<T> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

interface TokenPayload {
  access_token: string;
  access_expires_in: number;
  refresh_token: string;
  device_id: string;
  user?: IBrainUser;
}

async function call<T>(method: string, path: string, body?: unknown, token?: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BRAIN_URL + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
    });
  } catch {
    throw new BrainError("unreachable", UNREACHABLE);
  }
  const json = (await res.json().catch(() => null)) as Envelope<T> | null;
  if (json?.ok && json.data !== undefined) return json.data;
  if (json?.error) throw new BrainError(json.error.code, json.error.message);
  throw new BrainError("internal", "Something went sideways on the brain. Try again in a moment.");
}

class BrainAuth {
  private accessToken: string | null = null;
  private accessExpiresAt = 0;
  private refreshing: Promise<string> | null = null;

  async hasSession(): Promise<boolean> {
    return (await keytar.getPassword(KEYCHAIN_SERVICE, REFRESH_ACCOUNT)) !== null;
  }

  async deviceId(): Promise<string | null> {
    return keytar.getPassword(KEYCHAIN_SERVICE, DEVICE_ACCOUNT);
  }

  async startOtp(email: string): Promise<void> {
    await call("POST", "/v2/auth/otp/start", { email });
  }

  async verifyOtp(email: string, code: string): Promise<IBrainUser> {
    const device = { ...this.deviceInfo(), id: (await this.deviceId()) ?? undefined };
    const tokens = await call<TokenPayload>("POST", "/v2/auth/otp/verify", { email, code, device });
    await this.store(tokens);
    return tokens.user as IBrainUser;
  }

  /** RFC 8252: loopback listener + PKCE; the brain does the Google side (API.md §2.1). */
  async signInWithGoogle(): Promise<IBrainUser> {
    const verifier = crypto.randomBytes(48).toString("base64url");
    const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
    const { port, result } = await listenForCallback();
    const { name, platform } = this.deviceInfo();
    const params = new URLSearchParams({ device_name: name, platform, code_challenge: challenge, port: String(port) });
    const deviceId = await this.deviceId();
    if (deviceId) params.set("device_id", deviceId);
    await shell.openExternal(`${BRAIN_URL}/v2/auth/google/start?${params}`);

    const query = await result;
    const code = query.get("code");
    if (query.get("error") === "cancelled") {
      throw new BrainError("cancelled", "No worries, Google sign-in was cancelled.");
    }
    if (!code) throw new BrainError("unauthorized", "Google sign-in didn't go through. Give it another go.");
    const tokens = await call<TokenPayload>("POST", "/v2/auth/google/exchange", { code, code_verifier: verifier });
    await this.store(tokens);
    return tokens.user as IBrainUser;
  }

  async getAccessToken(): Promise<string> {
    if (this.accessToken && Date.now() < this.accessExpiresAt) return this.accessToken;
    return this.refresh();
  }

  /** Single flight: the brain revokes the session if an old refresh token is ever reused. */
  refresh(): Promise<string> {
    this.refreshing ??= this.doRefresh().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  async session(): Promise<IBrainSession> {
    try {
      return await call<IBrainSession>("GET", "/v2/me", undefined, await this.getAccessToken());
    } catch (err) {
      if (!(err instanceof BrainError) || err.code !== "unauthorized") throw err;
      return call<IBrainSession>("GET", "/v2/me", undefined, await this.refresh());
    }
  }

  async signOut(): Promise<void> {
    const token = this.accessToken;
    if (token) {
      // Best effort: the session is forgotten locally either way.
      await call("POST", "/v2/auth/logout", undefined, token).catch(() => undefined);
    }
    await this.forget();
  }

  private async doRefresh(): Promise<string> {
    const refreshToken = await keytar.getPassword(KEYCHAIN_SERVICE, REFRESH_ACCOUNT);
    if (!refreshToken) throw new BrainError("unauthorized", SIGNED_OUT);
    let tokens: TokenPayload;
    try {
      tokens = await call<TokenPayload>("POST", "/v2/auth/refresh", { refresh_token: refreshToken });
    } catch (err) {
      // Only a definite "no" from the brain ends the session; being offline keeps it.
      if (err instanceof BrainError && err.code === "unauthorized") await this.forget();
      throw err;
    }
    await this.store(tokens);
    return tokens.access_token;
  }

  private async store(tokens: TokenPayload): Promise<void> {
    this.accessToken = tokens.access_token;
    this.accessExpiresAt = Date.now() + (tokens.access_expires_in - 60) * 1000;
    await keytar.setPassword(KEYCHAIN_SERVICE, REFRESH_ACCOUNT, tokens.refresh_token);
    await keytar.setPassword(KEYCHAIN_SERVICE, DEVICE_ACCOUNT, tokens.device_id);
  }

  private async forget(): Promise<void> {
    this.accessToken = null;
    this.accessExpiresAt = 0;
    // The device id stays so the next sign-in keeps the same device.
    await keytar.deletePassword(KEYCHAIN_SERVICE, REFRESH_ACCOUNT);
  }

  deviceInfo(): { name: string; kind: "desktop"; platform: string; app_version: string } {
    return {
      name: os.hostname().slice(0, 60) || "Desktop",
      kind: "desktop",
      platform: process.platform,
      app_version: app.getVersion(),
    };
  }
}

function page(message: string): string {
  return (
    "<!doctype html><meta charset=utf-8><title>Spark</title>" +
    "<body style='font-family:system-ui;max-width:28rem;margin:20vh auto;text-align:center'>" +
    `<h2>Spark</h2><p>${message}</p></body>`
  );
}

function listenForCallback(): Promise<{ port: number; result: Promise<URLSearchParams> }> {
  return new Promise((resolveListening, rejectListening) => {
    let settle: { resolve: (q: URLSearchParams) => void; reject: (e: Error) => void };
    const result = new Promise<URLSearchParams>((resolve, reject) => {
      settle = { resolve, reject };
    });
    const server = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      if (url.pathname !== "/callback") {
        res.writeHead(404).end();
        return;
      }
      const ok = url.searchParams.has("code");
      res
        .writeHead(200, { "Content-Type": "text/html; charset=utf-8" })
        .end(page(ok ? "You're signed in. Head back to Spark." : "Sign-in didn't finish. Head back to Spark and try again."));
      clearTimeout(timer);
      server.close();
      settle.resolve(url.searchParams);
    });
    const timer = setTimeout(() => {
      server.close();
      settle.reject(new BrainError("timeout", "Google sign-in timed out. Give it another go."));
    }, GOOGLE_TIMEOUT_MS);
    server.on("error", rejectListening);
    server.listen(0, "127.0.0.1", () => {
      resolveListening({ port: (server.address() as AddressInfo).port, result });
    });
  });
}

export const brainAuth = new BrainAuth();
