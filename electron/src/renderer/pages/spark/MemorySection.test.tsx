// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import MemorySection, { type MemoryRow } from "./MemorySection";

const rows: MemoryRow[] = [
  { id: "m1", kind: "person", text: "The user's sister is Asha.", importance: 0.9, confirmed: true, last_used_at: null, expires_at: null, created_at: new Date().toISOString() },
  { id: "m2", kind: "fact", text: "The user's wifi is called Lotus.", importance: 0.8, confirmed: false, last_used_at: null, expires_at: null, created_at: new Date().toISOString() },
];
const request = vi.fn(async (method: string, path: string) => (method === "GET" && path === "/v2/memories" ? { ok: true, data: { items: rows } } : { ok: true, data: {} }));
(globalThis as unknown as { window: { electronApi: unknown } }).window.electronApi = { brain: { request } };
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Settings → Memory (TESTING §4.11 U7)", () => {
  it("lists memories and asks for an OK on the agent's", async () => {
    render(<MemorySection />);
    expect(await screen.findByText("The user's sister is Asha.")).toBeTruthy();
    expect(screen.getByText("needs your OK")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Keep: The user's wifi is called Lotus."));
    await waitFor(() => expect(request).toHaveBeenCalledWith("PATCH", "/v2/memories/m2", { confirmed: true }));
  });

  it("edits a memory in place", async () => {
    render(<MemorySection />);
    fireEvent.click(await screen.findByLabelText("Edit: The user's sister is Asha."));
    fireEvent.change(screen.getByLabelText("Memory"), { target: { value: " The user's sister is Asha Rai. " } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(request).toHaveBeenCalledWith("PATCH", "/v2/memories/m1", { text: "The user's sister is Asha Rai." }));
  });

  it("forgets only after a yes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<MemorySection />);
    const trash = await screen.findByLabelText("Forget: The user's sister is Asha.");
    fireEvent.click(trash);
    expect(request).not.toHaveBeenCalledWith("DELETE", "/v2/memories/m1", undefined);
    fireEvent.click(trash);
    await waitFor(() => expect(request).toHaveBeenCalledWith("DELETE", "/v2/memories/m1", undefined));
    confirm.mockRestore();
  });

  it("has an empty state and searches as you type", async () => {
    request.mockImplementation(async () => ({ ok: true, data: { items: [] } }));
    render(<MemorySection />);
    expect(await screen.findByText(/Nothing yet/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search memories"), { target: { value: "asha" } });
    await waitFor(() => expect(request).toHaveBeenCalledWith("GET", "/v2/memories?q=asha"));
    expect(await screen.findByText("Nothing matches that.")).toBeTruthy();
  });
});
