// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ApprovalView, AskView, JobView } from "@/store/features/spark/sparkSlice";
import { ApprovalCard, AskCard } from "./Cards";
import { JobPanel } from "@/pages/spark/HomePage";

const api = {
  brain: { approve: vi.fn(), answer: vi.fn(), cancelJob: vi.fn() },
};
(globalThis as unknown as { window: { electronApi: unknown } }).window.electronApi = api;
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const approval: ApprovalView = {
  id: "a1",
  jobId: "j1",
  tool: "file_delete",
  summary: "Delete 6 installers in Downloads",
  inputs: { path: "C:/Users/asha/Downloads/Installers/*.exe", device: "Laptop" },
  risk: "destructive",
  options: ["allow", "deny", "always"],
};

describe("approval card (TESTING §4.11)", () => {
  it("shows the exact inputs and sends the answer", () => {
    render(<ApprovalCard approval={approval} full />);
    expect(screen.getByText("C:/Users/asha/Downloads/Installers/*.exe")).toBeTruthy();
    expect(screen.getByText("Laptop")).toBeTruthy();
    fireEvent.click(screen.getByText("Allow"));
    expect(api.brain.approve).toHaveBeenCalledWith("a1", "allow");
    fireEvent.click(screen.getByText("Always allow"));
    expect(api.brain.approve).toHaveBeenLastCalledWith("a1", "always");
  });

  it("puts the focus on Deny for destructive actions", () => {
    render(<ApprovalCard approval={approval} full />);
    expect(document.activeElement?.textContent).toBe("Deny");
  });
});

describe("question card", () => {
  it("answers with a chip, or with typed text when there are no options", () => {
    const ask: AskView = { id: "q1", jobId: "j1", question: "Desktop or Documents?", options: ["Desktop", "Documents"] };
    render(<AskCard ask={ask} />);
    fireEvent.click(screen.getByText("Documents"));
    expect(api.brain.answer).toHaveBeenCalledWith("q1", "Documents");
    cleanup();
    render(<AskCard ask={{ ...ask, id: "q2", options: [] }} />);
    const box = screen.getByLabelText("Desktop or Documents?");
    fireEvent.change(box, { target: { value: "  my D drive " } });
    fireEvent.submit(box.closest("form")!);
    expect(api.brain.answer).toHaveBeenLastCalledWith("q2", "my D drive");
  });
});

describe("job panel (TESTING §4.11)", () => {
  const job: JobView = {
    id: "j1",
    title: "Clean up Downloads",
    status: "running",
    todo: [
      { text: "Look through Downloads", status: "done" },
      { text: "Delete old installers", status: "in_progress" },
    ],
    etaS: 20,
    steps: [{ id: "s1", tool: "file_list", summary: "48 items", status: "ok", deviceId: null }],
    note: "Found six installers older than a year.",
    summary: null,
    artifactId: null,
  };

  it("shows the checklist, steps and note, and Stop cancels the job", () => {
    render(<JobPanel job={job} recent={[]} />);
    expect(screen.getByText("Delete old installers")).toBeTruthy();
    expect(screen.getByText("48 items")).toBeTruthy();
    expect(screen.getByText("About 20 seconds left")).toBeTruthy();
    fireEvent.click(screen.getByText("Stop"));
    expect(api.brain.cancelJob).toHaveBeenCalledWith("j1");
  });

  it("with nothing running, lists recent jobs or says what shows up here", () => {
    render(<JobPanel job={null} recent={[]} />);
    expect(screen.getByText("Nothing running")).toBeTruthy();
    expect(screen.getByText(/checklist and a Stop button/)).toBeTruthy();
  });
});
