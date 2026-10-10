# DESIGN.md — Desktop UI Guidelines (v2)

Applies to `electron/src/renderer`. Information architecture is in `REDESIGN.md` §24; voice and
copy in `PERSONA.md`. Tokens live in `electron/src/renderer/index.css`.

## 1. Principles

1. **Voice first, screen second.** The UI confirms what Spark heard, shows what it's doing, and
   asks for approval. It never demands attention.
2. **Show work live.** Jobs, steps, approvals, and engine switches are visible as they happen.
3. **Instant feel.** Optimistic UI for local actions; skeletons within 100 ms; no layout jumps.
4. **Clean, calm, dark.** Neutral grays with one orange accent (owner, 2026-10-10).
5. **Professional.** Every action shows its inputs and result; nothing shows a raw error.

## 2. Foundation

### 2.1 Color tokens (`--sp-*`)
| Token | Value | Use |
|---|---|---|
| `--sp-bg` / `--sp-bg-2` / `--sp-bg-3` | `#0f1012` / `#15171a` / `#1c1f23` | app / panels / raised |
| `--sp-line` / `--sp-line-2` | `#24272c` / `#2e3238` | borders |
| `--sp-ink` → `--sp-ink-4` | `#eceef1` → `#4f545b` | text, primary → disabled |
| `--sp-accent` / `--sp-accent-2` / `--sp-accent-soft` | `#f97316` / `#ea580c` / 12% | the only accent: primary action, focus, Spark identity |
| `--sp-ok` / `--sp-warn` / `--sp-err` / `--sp-info` (+ `-soft`) | `#4ade80` / `#facc15` / `#f87171` / `#60a5fa` | status |

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
Geist for everything, Spark's replies included (a clean look; the owner dropped the serif on
2026-10-10), Geist Mono (paths, commands, tool inputs), Science Gothic (brand moments only).
Mockups: `docs/mockups/r2-ui.html`.

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

Global: left rail, **Ctrl+K command palette** (every action and setting), and the **voice overlay**.

**Voice overlay** (`pages/overlay/`, the always-on-top window): Spark's main voice surface, a notch
hanging from the top edge of the screen. Flat top with concave flares into the edge, rounded bottom,
solid near-black (no glass: a window can't blur the desktop). Resting: a 196 px pill (orb, "Spark",
mic state). Live job: a 340 px pill (title, n/m). Full (560 px) while listening, thinking, speaking,
waiting on you, on hover, and for 7 s after a reply: what you said (small, muted), Spark's reply
(15.5 px, streaming), the job row with Stop, the approval card (risk dot, summary, exact inputs,
Deny / Always allow / Allow) or the question, and on hover the mic toggle, a text box and "open
Spark". The orb is orange; its halo, an in-notch glow and a bloom along the bottom edge follow
Spark's real voice level (the mic's while listening). Motion: one near-critically-damped spring
for the shape, 200 ms blur-fades for content; `prefers-reduced-motion` stops it. The window never
moves or resizes; it is click-through except over the notch.

## 4. Key components

| Component | Contract |
|---|---|
| **Conversation** | user turns in a bubble, Spark replies as plain text, inline artifacts, citations; streaming text appears as it's spoken |
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
