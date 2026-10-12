import { describe, expect, it } from "vitest";
import { BRAIN_PATH } from "../main/ipc/brainPaths";

// Main only forwards allowlisted brain routes. The Memory page shipped calling /v2/memories before
// main allowed it (2026-10-11): every route the renderer names must pass, and auth never.
const sources = import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.*"], { query: "?raw", import: "default", eager: true });

describe("brain routes through main", () => {
  it("allows every route the renderer calls", () => {
    const routes = Object.values(sources).flatMap((src) => [...src.matchAll(/["`](\/v2\/[^"`]*)["`]/g)].map((m) => m[1].replace(/\$\{[^}]*\}/g, "x1")));
    expect(routes.length).toBeGreaterThan(5);
    expect(routes.filter((r) => !BRAIN_PATH.test(r))).toEqual([]);
  });

  it("never auth, never a way out", () => {
    for (const bad of ["/v2/auth/refresh", "/v2/memories/../auth/refresh", "https://evil.example/v2/jobs", "/v2/jobs?x=<script>"]) expect(BRAIN_PATH.test(bad)).toBe(false);
  });
});
