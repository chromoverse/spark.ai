# DESIGN.md — Desktop UI Guidelines (v2)

Applies to `electron/src/renderer`. Information architecture is in `REDESIGN.md` §24; voice and
copy in `PERSONA.md`. Tokens live in `electron/src/renderer/index.css`.

## 1. Principles

1. **Voice first, screen second.** The UI confirms what Spark heard, shows what it's doing, and
   asks for approval. It never demands attention.
2. **Show work live.** Jobs, steps, approvals, and engine switches are visible as they happen.
3. **Instant feel.** Optimistic UI for local actions; skeletons within 100 ms; no layout jumps.
4. **Calm, warm, dark.** Warm neutrals with one terracotta accent.
5. **Professional.** Every action shows its inputs and result; nothing shows a raw error.

## 2. Foundation

### 2.1 Color tokens (`--sp-*`)
| Token | Value | Use |
|---|---|---|
| `--sp-bg` / `--sp-bg-2` / `--sp-bg-3` | `#161512` / `#1c1b17` / `#232118` | app / panels / raised |
| `--sp-line` / `--sp-line-2` | `#2a2822` / `#34312a` | borders |
| `--sp-ink` → `--sp-ink-4` | `#ece6da` → `#524d44` | text, primary → disabled |
| `--sp-accent` / `--sp-accent-2` / `--sp-accent-soft` | `#d97757` / `#c2643f` / 12% | primary action, focus, Spark identity |
| `--sp-ok` / `--sp-warn` / `--sp-err` / `--sp-info` (+ `-soft`) | `#7fb685` / `#d4a04a` / `#c97064` / `#87a7c4` | status |

shadcn tokens back `components/ui`. New UI uses `--sp-*` only.

### 2.2 Status mapping
| State | Token |
|---|---|
| running | `--sp-info` |
| done | `--sp-ok` |
| needs you (approval, connect, question) | `--sp-warn` |
| failed (explained) | `--sp-err` |
| queued / idle | `--sp-ink-3` |

### 2.3 Typography
Geist (UI), Instrument Serif (Spark's spoken reply, warm headings), Geist Mono (paths, commands,
tool inputs), Science Gothic (brand moments only).

### 2.4 Spacing, radius, icons
Tailwind 4 px scale; `--radius: 0.625rem`; lucide icons (16 px inline, 20 px buttons).

## 3. Layout — five destinations

| Destination | Purpose | Key components |
|---|---|---|
| **Home** | talk and watch work happen | Conversation, ArtifactView, JobPanel, ApprovalCard, ConnectCard, AskCard, InputBar (mic + text), DeviceSwitcher |
| **Activity** | what happened and what's scheduled | JobHistory, Schedules & Automations, Incidents, Logs |
| **Capabilities** | what Spark can do | one search + chips: Connectors · Skills · Plugins · Tools; Discover (marketplace, MCP Registry) |
| **Engines** | how Spark runs on this device | Models (chains + health, local models), Voice (engine plan + benchmark scores + voice picker), Services, Keys |
| **Settings** | you and your data | Account, Devices, Permissions (mode + rules), Privacy (training-provider toggle, Memory, export/delete), Language, Verbosity & nickname, Usage |

Global: left rail, **Ctrl+K command palette** (every action and setting), compact **voice overlay**
(always-on-top mini panel with the waveform, live transcript, and reply).

## 4. Key components

| Component | Contract |
|---|---|
| **Conversation** | user turns, Spark replies (serif), inline artifacts, citations; streaming text appears as it's spoken |
| **JobPanel** | todo checklist, live steps (tool, target device, status color), progress notes, ETA, **Stop** |
| **ApprovalCard** | exact inputs (recipient, path, command, amount) in mono; risk label; Allow / Always allow / Deny; default focus on Deny for destructive actions; arrives on all devices, the first answer wins |
| **ConnectCard** | "I need Gmail access for that" + **Connect Google**; after OAuth the job resumes and the card turns into a check mark |
| **AskCard** | the question + option chips; can also be answered by voice |
| **ArtifactView** | table (sortable, export CSV), chart (interactive Vega-Lite, export PNG), image, audio, video, document, map, entity cards; "open in app", "send to phone" |
| **EnginePlanCard** | per role: ranked engines with measured latency, active engine highlighted, last switch reason; **Run benchmark** |
| **ChainHealth** | each provider in a chain: free/paid, healthy/cooling, TTFT, quota left |
| **CapabilityRow** | name, source (built-in / skill / plugin / MCP), risk, permission rule, context cost, toggle |
| **DeviceSwitcher** | "Run on: Laptop · Phone (USB)"; presence dots |
| **Toasts (sonner)** | short, persona-voiced; errors offer a fix action |

## 5. States every view must handle

- **Loading:** skeleton within 100 ms; never a blank panel.
- **Empty:** one friendly line + one action ("No skills yet. Import one or ask Spark to make one.").
- **Error:** what failed + how to fix + Retry, in persona voice. Never raw text like `'id'` or `HttpError 400`.
- **Offline / brain unreachable:** banner "Running on the local model, basics only" with details.
- **Populated.**

## 6. Accessibility

Keyboard reachable everywhere, visible focus ring (`--sp-accent`); `aria-label` on icon buttons;
contrast ≥ 4.5:1 for body text; `aria-live="polite"` for replies and job status; reduced motion
respected; the mic state is always visible.

## 7. Motion

`motion` library; 150–250 ms ease-out; ambient animations pause when the window is hidden and stop
under reduced motion. Streaming text and steps animate in without shifting layout.

## 8. Copy

Follows `PERSONA.md`: short, warm, active verbs ("Connect Google", "Run benchmark", "Try again").
No jargon, no blame, no exclamation spam.

## 9. Don'ts

New colors outside tokens; styled-components or react-icons in new code; modals for information
that fits inline; auto-dismissing errors or approvals; raw stack traces; one-tab-per-feature
sprawl (group into the five destinations).
