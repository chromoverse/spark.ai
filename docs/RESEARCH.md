# RESEARCH.md — Agent Platforms & Providers (2026-10-09)

Research behind `REDESIGN.md` v2. Covers how Claude Code and Codex do tools, skills, plugins,
MCP, permissions, and context, plus the state of free LLM/STT/TTS options as of October 2026.
Provider limits change often, so re-check the sources before relying on numbers.

---

## 1. Claude Code (Anthropic)

| Area | How it works | Source |
|---|---|---|
| Agent loop | gather context → act → verify, repeat; user can interrupt (Esc) or queue a steering message that the agent reads after its current tool calls | [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) |
| Built-in tools | file ops, search, execution (shell), web, code intelligence + orchestration tools (subagents, ask user) | same |
| Context | auto-compaction (clears old tool outputs first, then summarizes); MCP tool definitions **deferred by default** and loaded via tool search, so only tool names cost context | same |
| Memory | `CLAUDE.md` (always loaded) + auto memory `MEMORY.md` (first 200 lines / 25 KB loaded at session start) | same |
| Subagents | Markdown + frontmatter (`name`, `description`, `tools`, `model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `effort`, `background`); fresh isolated context; only the final report returns; cheap models (Haiku) for exploration; 20 concurrent by default, nesting depth 3; delegation descriptions kept under ~15k tokens total | [Subagents](https://code.claude.com/docs/en/sub-agents) |
| Skills | `SKILL.md` folders (Agent Skills open standard, [agentskills.io](https://agentskills.io)); **progressive disclosure**: name + description always loaded (≤1,536 chars), body loaded on use, `scripts/` executed (never loaded), reference files loaded on demand; `disable-model-invocation`, `allowed-tools`, `context: fork` | [Skills](https://code.claude.com/docs/en/skills) |
| Plugins | a directory bundling skills, agents, hooks, MCP servers; manifest `.claude-plugin/plugin.json`; **marketplaces** are git repos with `marketplace.json`; install scopes user/project/local; shows a per-plugin **context-cost** estimate | [Plugins](https://code.claude.com/docs/en/plugins) |
| Hooks | ~30 lifecycle events (`PreToolUse`, `PostToolUse`, `PostToolBatch`, `PermissionRequest`, `UserPromptSubmit`, `SessionStart`, `PreCompact`, `Stop`, `SubagentStop`, `Elicitation`…); types command / http / mcp_tool / prompt / agent; can deny, ask, rewrite input (`updatedInput`), inject context, replace tool output | [Hooks](https://code.claude.com/docs/en/hooks) |
| MCP | stdio / streamable HTTP / (deprecated SSE) / WebSocket; OAuth with RFC 9728 + RFC 8414 discovery and token refresh; output warning at 10k tokens, cap 25k tokens, >50k chars saved to a file with a path reference; long calls auto-background after 2 min | [MCP](https://code.claude.com/docs/en/mcp) |
| Permissions | modes: auto (background **classifier** reviews actions), manual, accept edits, plan; rules `Tool(specifier)` with wildcards; **deny → ask → allow** precedence; deny on a bare tool name removes it from context; built-in read-only command set never prompts | [Permissions](https://code.claude.com/docs/en/permissions) |
| Safety net | file checkpoints before edits (rewind) | How Claude Code works |

## 2. OpenAI Codex

| Area | How it works | Source |
|---|---|---|
| Sandbox | `read-only` / `workspace-write` / `danger-full-access`; named permission profiles with filesystem read/write/deny globs and network rules | [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference) |
| Approvals | `on-request` / `never`, plus **granular** categories (sandbox, rules, MCP elicitations, permission requests, skills); **`auto_review`** routes eligible approvals to a reviewer subagent; flexible approvals ask for a specific extra permission instead of a mode change | same; [CLI reference](https://developers.openai.com/codex/cli/reference) |
| MCP | per-server and per-tool approval mode `auto` / `prompt` / `writes` / `approve`; `enabled_tools` / `disabled_tools`; startup 10 s and tool 60 s timeouts; `required` servers; per-tool `output_token_limit` | Config reference |
| Skills | `SKILL.md` + `scripts/`, `references/`, `assets/`, `agents/openai.yaml`; catalog capped at **2% of context** (≤10k tokens), descriptions shortened first; explicit (`$skill`) or implicit invocation; built-in `skill-creator`, `skill-installer` | [Build skills](https://learn.chatgpt.com/docs/build-skills) |
| Plugins | `plugin@marketplace` keys; marketplaces from git; bundled MCP servers tunable per plugin | Config reference |
| Hooks | `PreToolUse`, `PostToolUse`, `PermissionRequest`, `SessionStart/End`, `Stop`, `UserPromptSubmit`, `PreCompact/PostCompact`, subagent start/stop; oversized hook context saved to disk with a preview | Config reference |
| Memory | opt-in memory generation with **governance**: age and idle thresholds, expiry of unused memories, rate-limit headroom, and exclusion of threads that touched external content (MCP, web) | Config reference |
| Subagents | spawn / send / resume / wait / close tools; per-session concurrency cap; default subagent model + effort | Config reference |
| Secrets | env vars containing KEY / SECRET / TOKEN stripped before tool execution | Config reference |

## 3. Model Context Protocol (spec 2026-07-28)

- Tool = `name`, `title`, `description`, `inputSchema`, optional **`outputSchema`**, `annotations`, `icons`.
  Results can return `structuredContent` (validated against `outputSchema`) plus text, image,
  audio, `resource_link`, or embedded resources.
- **Annotations** (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are
  hints and **must be treated as untrusted** unless the server is trusted.
- Servers **should return tools in deterministic order**, which helps clients cache and raises prompt-cache hit rates.
- Two error kinds: protocol errors vs tool execution errors (`isError: true`, actionable text the
  model can self-correct from).
- `input_required` results drive multi-round-trip **elicitation** (a form shown to the user mid-call).
- Stateful tools use explicit handles (`basket_id`) with stated lifetimes.
- Clients should show tool inputs before calling, confirm sensitive operations, enforce timeouts, and audit.
- Source: [MCP tools spec](https://modelcontextprotocol.io/specification/latest/server/tools)

## 4. Anthropic engineering guidance

**Writing tools for agents** ([article](https://www.anthropic.com/engineering/writing-tools-for-agents)):
- Build fewer, workflow-shaped tools (`schedule_event` beats `list_users` + `list_events` + `create_event`).
- Namespace tools by service (`gmail_search`, `slack_post`).
- Return readable fields instead of UUIDs, and offer a `response_format: concise | detailed` option
  (concise ≈ ⅓ the tokens).
- Paginate, filter, and truncate with defaults (Claude Code caps output at 25k tokens), and tell the
  agent how to narrow the query.
- Make error messages actionable.
- Describe tools as you would to a new hire.
- Iterate with evals that track accuracy, tool-call count, tokens, and errors.

**Code execution with MCP** ([article](https://www.anthropic.com/engineering/code-execution-with-mcp)):
- Expose tools as code APIs on a filesystem. The agent discovers them progressively and writes a
  script, so intermediate data never passes through the model.
- A Drive→Salesforce workflow went from ~150k to ~2k tokens (−98.7%). Filtering 10k rows shows the model 5.
- Bonus: PII can be tokenized before it reaches the model, and working scripts can be saved as skills.
- Cost: needs a secure sandbox.

**Claude API agent design** (claude-api skill): promote an action to a dedicated tool when you need
to gate, render, audit, or parallelize it; use tool search to append schemas without breaking the
cache; mid-conversation system messages for new context; subagents for a second model.

## 5. Free-tier reality (October 2026)

| Provider | Free offer now | Limits | Notes | Sources |
|---|---|---|---|---|
| **Groq** chat | free plan | `gpt-oss-120b` / `gpt-oss-20b` / `qwen3.8-27b`: 30 RPM, **1K req/day, 8K tokens/min**, 200K tokens/day | limits are **per organization**; Llama models gone | [Groq rate limits](https://console.groq.com/docs/rate-limits) |
| **Groq** Whisper STT | free plan | 20 RPM, 2K req/day, 7.2K audio-sec/hour | `whisper-large-v3-turbo` | same |
| **Groq** Orpheus TTS | free plan | **10 RPM, 100 req/day**, ≤200 chars/request, WAV | expressive `[cheerful]`-style vocal directions; ~200 ms to first byte; paid $22 / 1M chars | [Groq Orpheus](https://console.groq.com/docs/text-to-speech/orpheus), [Katonic production notes](https://www.katonic.ai/blog/groq-orpheus-production) |
| **Gemini** | free tier on Flash / Flash-Lite only | Flash ≈ 20 req/day, Flash-Lite ≈ 500 req/day, per project | **free-tier data used to improve Google products**; multimodal (image, audio, video) input on free tier; Pro is paid-only | [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **Cerebras** | **no recurring free tier** since mid-2026 | $5 one-time trial | `gpt-oss-120b` paid $0.35 / $0.75 per MTok | [Cerebras free tier notes](https://benchlm.ai/free-tier/cerebras) |
| **OpenRouter** `:free` | free | 20 RPM, **50 req/day** (1,000/day after a one-time $10 credit purchase) | model pool changes often; `openrouter/free` router picks a model that supports tools | [OpenRouter limits](https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know) |
| **edge-tts** | free, unofficial | undocumented | Microsoft Edge read-aloud endpoint; **datacenter/VPN IPs get blocked**, intermittent 403/503, needs edge-tts ≥ 7.2.2 → run it **on the user's device**, never from the brain VPS, and keep a fallback | [edge-tts issues](https://github.com/rany2/edge-tts/issues) |
| **NVIDIA build.nvidia.com** (free endpoints) | free, NVIDIA Developer account | ~40 RPM per model (one roundup: 10K req/day per model) | ~80 hosted models incl. DeepSeek V4 Pro/Flash, Kimi K3, Nemotron 3 Super/Ultra, gpt-oss-20b; **for prototyping/testing only**; shared endpoints → latency varies (agent, not reflex) | [klymentiev verified list](https://klymentiev.com/blog/free-llm-api), [DEV Oct 2026](https://dev.to/tariqnasser/free-llm-api-tiers-in-october-2026-whats-left-and-how-i-chain-them-227l) |
| **Cloudflare Workers AI** | free, no card | 10,000 Neurons/day shared across models; 300 RPM text (20 RPM on large models) | gpt-oss-120b/20b, Llama 3.3 70B, Qwen3 30B, QwQ 32B, Gemma 3/4, Kimi K2.5, GLM-4.7-Flash; **does not train on your content** | same |
| **Mistral** (La Plateforme, Free mode) | free, no card | $10/month credits | Large 3, Medium 3.5, Small 4, Codestral; Free mode may train on data **unless you opt out** | same |
| **Google AI Studio — Gemma** | free | per-project caps in AI Studio | Gemma 4 31B / 26B-A4B; same data terms as Gemini free | same |
| **Cohere** (trial key) | free | 1,000 calls/month, 20 RPM chat | Command A / A Reasoning; **non-commercial only** | same |
| **Hugging Face** Inference Providers | free | $0.10/month credit | routes to partner providers | same |
| **Z AI** (GLM-4.7-Flash) | free | 1 concurrent request | — | DEV Oct 2026 |
| No longer free | — | — | GitHub Models (retired 30 Jul 2026), Together AI ($5 minimum), Chutes, SambaNova (new accounts buy credits), Cerebras ($5 trial) | klymentiev |
| Claude Haiku 5.5 | paid | — | $0.10 / $0.50 per MTok: the **cheapest capable paid** option, cheaper than paid `gpt-oss-120b` on Cerebras | claude-api skill |

**Latency fit (to be measured from the brain region in R0/R1):** Groq is the fastest free option and the only one
assumed reflex-grade (< 1 s) up front; Cloudflare Workers AI, Gemini Flash-Lite, and Mistral Small are
reflex candidates if they measure p95 time-to-first-token ≤ 400 ms; NVIDIA free endpoints, OpenRouter free,
and Cohere are agent/background only (variable queueing).

**Implication:** free tiers are per account and small. One shared platform key serves only a
handful of users. Free capacity that scales comes from:
1. **On-device compute**: STT, TTS, embeddings, and local LLMs on strong machines.
2. **Each user's own free keys**: a guided "get a free Groq key" flow gives each user their own
   ~1K requests/day for chat, ~2K for STT, and 100 expressive TTS clips.
3. **Self-hosted open source**: SearXNG, OpenStreetMap.
4. **A small platform free-key pool** for trials.

After that, the cheapest capable paid model (Haiku 5.5) is the right last resort.

## 6. Local TTS on CPU (benchmarks vary by hardware; verify on-device)

| Engine | Notes | Source |
|---|---|---|
| Kokoro-82M | high quality, no emotion control; first-audio on CPU reported from **<1 s (M3) to ~3.5 s (older i7)** | [Picovoice on-device TTS](https://picovoice.ai/blog/on-device-tts/), [comparison](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026) |
| Pocket TTS (Kyutai) | ~200 ms first chunk, ~6× real-time on 2 CPU cores, voice cloning | [Pocket TTS](https://kyutai-labs.github.io/pocket-tts/) |
| Chatterbox Turbo / Nano | expressive tags ([laugh], [sigh]…), Nano ~3× real-time on 8 cores | [Chatterbox](https://github.com/resemble-ai/chatterbox) |
| Orpheus 3B (open weights) | most expressive; needs a GPU for real-time | [Orpheus](https://github.com/canopyai/Orpheus-TTS) |
| Kitten TTS | tiny (15–80M) but no streaming (≈10 s to first audio) → not for live voice | Picovoice |

**Implication:** a fixed engine choice can't meet 1 s on every machine. Engines must be
**benchmarked on each device** and picked per device (`REDESIGN.md` §18).

## 7. What Spark adopts, and where it goes further

| Idea | From | Spark v2 |
|---|---|---|
| Single tool-calling agent loop with interrupt and steering | Claude Code | §5.2; voice barge-in and "steer" signals (§6.4) |
| Deferred tool loading / tool search | Claude Code, Claude API | §5.2 + local BM25 preselect for non-Claude models |
| Skills with progressive disclosure, Agent Skills standard | Claude Code, Codex | §20: **import skills made for Claude Code / Codex as-is** |
| Plugins + git marketplaces with context-cost display | Claude Code, Codex | §20 |
| Hooks with deny / ask / rewrite / inject | Claude Code, Codex | §20 |
| deny → ask → allow rules, modes, auto-review classifier | Claude Code, Codex | §7.2 + §20 auto-reviewer |
| MCP annotations → risk, per-server approval modes, output caps, overflow to file | MCP spec, Codex, Claude Code | §20 |
| Code-execution "workflow mode" for multi-tool data flows | Anthropic engineering | §21 |
| Memory governance (expiry, exclude external-content threads) | Codex | §8 |
| **Beyond them:** voice-first < 1 s, multi-device body with phone control, per-device engine benchmarking, a supervisor that guarantees no silent failure, free-first cost routing, proactive scheduling | — | §4, §18, §19, §5.5 |
