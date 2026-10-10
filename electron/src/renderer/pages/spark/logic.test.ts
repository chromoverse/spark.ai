import { describe, expect, it } from "vitest";
import { ago, bareRules, filterCommands, fmtEta, matches, type Command, type Rule, type ToolRow } from "./logic";

const cmd = (label: string, group = "Go to", keywords = ""): Command => ({ id: label, group, label, keywords, run: () => {} });

describe("Ctrl+K palette", () => {
  const all = [cmd("Home"), cmd("Permissions", "Settings", "rules mode approvals"), cmd("Run engine benchmark", "Actions", "voice speed"), cmd("Sign out", "Actions", "log out")];

  it("finds by the start of any word, in label, keywords or group", () => {
    expect(filterCommands(all, "perm").map((c) => c.label)).toEqual(["Permissions"]);
    expect(filterCommands(all, "rules").map((c) => c.label)).toEqual(["Permissions"]);
    expect(filterCommands(all, "bench").map((c) => c.label)).toEqual(["Run engine benchmark"]);
    expect(filterCommands(all, "log out").map((c) => c.label)).toEqual(["Sign out"]);
  });

  it("shows everything when empty and nothing on a miss", () => {
    expect(filterCommands(all, "  ")).toHaveLength(4);
    expect(filterCommands(all, "zzz")).toEqual([]);
  });
});

describe("Capabilities", () => {
  const tool: ToolRow = { name: "clipboard_read", description: "Reads the text on the clipboard", target: "device", risk: "read", permission: "allow" };

  it("search matches words of the name and the description", () => {
    expect(matches(tool, "clipboard")).toBe(true);
    expect(matches(tool, "clip read")).toBe(true);
    expect(matches(tool, "text")).toBe(true);
    expect(matches(tool, "delete")).toBe(false);
  });

  it("the three-way control owns only bare rules (no pattern, every device)", () => {
    const rules: Rule[] = [
      { id: "1", tool: "file_delete", pattern: "", decision: "ask", device_id: null },
      { id: "2", tool: "file_delete", pattern: "C:/Users/*/Documents/**", decision: "deny", device_id: null },
      { id: "3", tool: "file_delete", pattern: "", decision: "allow", device_id: "laptop" },
      { id: "4", tool: "shell_run", pattern: "", decision: "deny", device_id: null },
    ];
    expect(bareRules(rules, "file_delete").map((r) => r.id)).toEqual(["1"]);
  });
});

describe("time copy", () => {
  it("says estimates and ages the way people do", () => {
    expect(fmtEta(20)).toBe("20 seconds");
    expect(fmtEta(70)).toBe("a minute");
    expect(fmtEta(300)).toBe("5 minutes");
    const now = Date.parse("2026-10-10T12:00:00Z");
    expect(ago("2026-10-10T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-10-10T11:56:00Z", now)).toBe("4 min ago");
    expect(ago("2026-10-10T09:00:00Z", now)).toBe("3 h ago");
    expect(ago(null, now)).toBe("");
  });
});
