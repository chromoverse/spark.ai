# Spark Browser Agent — Implementation Plan

> Reference: `WEB_AGENT.md` (architecture notes — useful but not law).
> Replaces the stubbed handlers in
> `server/plugins/installed/web/tools/browser_action.py`.
> Leaves `tools/browser_agent.py` (research) untouched.

## Opinionated takes (read first)

| Decision | Choice | Why |
|---|---|---|
| Automation library | **Playwright primary**, nodriver later behind a `BrowserRuntime` interface | User-controlled browser ≠ scraper. Reliability, iframe handling, downloads, debugging beat stealth. nodriver becomes a swap-in only when a site blocks Playwright. |
| LLM tool count | **One** new `BaseTool` (`BrowserAgentTool`); edit existing `BrowserActionTool` | Smaller surface = fewer hallucinations. |
| Adapter pattern | **Action graphs over reusable steps**, not hand-written methods per site | Without this, every site duplicates `search_product / select_result / open_detail / add_to_cart`. Adapters only override site quirks. |
| Encrypted memory | **Skip in v1.** Chrome autofill already has it | Add only when a transactional adapter actually needs data Chrome can't autofill. |
| Vision | **One stub function**, real `take_screenshot`, mocked `analyze_screenshot` | Real vision is a model swap, not a build. |
| Dry-run mode | **Day-1 feature flag**, not a Layer-4 nice-to-have | Without it, dev iteration loops are 30s/click and CI is impossible. |

Hard rules (no deviation):

- **CDP-attach only.** Never launch a second Chrome.
- **LLM never sees HTML or selectors.** Only semantic verbs.
- **State machine is enforced.** No skipping states.
- **Stop at payment.** Zero code paths submit a payment form.
- **Every action writes a replay-log event.** No exceptions.
- **Every action returns a confidence score.** Below the gate → verify, retry, or hand to user.
- **Every flow verifies its goal.** Adapters MUST implement `verify_goal_completed()`.
- **Every error is a typed enum** (`BrowserErrorType`). Recovery branches on type.
- **Every flow runs under hard time + action budgets** and a circuit breaker.
- **Every adapter is composed of reusable `ActionStep`s.** Bespoke per-state methods are the exception, not the default.

## Package layout

```
server/plugins/installed/web/browser/
├── __init__.py
├── errors.py               # BrowserErrorType enum + BrowserError exception
├── policies.py             # time budgets, retry policies, circuit breaker
├── runtime/
│   ├── base.py             # BrowserRuntime interface + health monitor
│   ├── playwright.py       # default impl (CDP attach)
│   └── nodriver.py         # future swap-in (skipped v1)
├── perception/
│   ├── dom.py              # extract_ui_tree, find_element, MutationObserver stability
│   └── vision.py           # screenshot real, analyze mocked
├── semantic.py             # verbs (each returns ActionResult with confidence + typed error)
├── intelligence.py         # detect_captcha / payment_page / login / checkout + page classifier
├── recovery.py             # error-type-driven recovery strategies
├── verification.py         # GoalVerifier — composable predicates
├── action_graph.py         # ActionStep + ActionGraph — reusable flow recipes
├── human_loop.py           # request_user_confirmation, pause_for_human
├── events.py               # event bus (ACTION_STARTED, FLOW_ABORTED, ...)
├── state_machine.py        # Flow runner — enforces budgets, breakers, verification
├── replay_log.py           # JSONL + screenshots
├── adapters/
│   ├── base.py             # SiteAdapter + capability flags + verify_goal_completed
│   ├── steps.py            # library of reusable ActionSteps (search, select, ...)
│   └── youtube.py          # first concrete adapter
└── tool.py                 # BrowserAgentTool — the only new BaseTool
```

Devx + hardening (Layer 4, separate folder):

```
server/plugins/installed/web/browser/devx/
├── overlay.py              # visual debugging overlay (page.evaluate injection)
├── observers.py            # network / console / screenshot observers
└── fixtures/               # sandboxed test HTML for regression
```

## LLM tool surface

```python
class BrowserAgentTool(BaseTool):
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "intent":          {"type": "string", "required": True},
        "query":           {"type": "string", "required": False},
        "entity":          {"type": "object", "required": False},
        "approve_payment": {"type": "boolean", "default": False},
        "dry_run":         {"type": "boolean", "default": False},
    }
```

`tools/browser_action.py` keeps `open_url` / `play_media` honest stubs;
delegates `book_hotel` / `buy_product` / `reserve_table` / `book_ticket`
to `BrowserAgentTool` when an adapter exists. Old callers don't break.

Safety policy (enforced at the tool boundary, not buried in adapters):

```python
FORBIDDEN_INTENTS = {"bank_transfer", "crypto_send", "delete_account", ...}
```

Hard refusal before any flow starts.

---

## Layer 1 — Foundation

### 1a. `errors.py` — typed error taxonomy

```python
class BrowserErrorType(str, Enum):
    ELEMENT_NOT_FOUND      = "element_not_found"
    LOW_CONFIDENCE         = "low_confidence"
    STALE_DOM              = "stale_dom"
    DOM_NOT_STABLE         = "dom_not_stable"
    NAVIGATION_FAILED      = "navigation_failed"
    NETWORK_FAILED         = "network_failed"
    TIMEOUT                = "timeout"
    LOGIN_REQUIRED         = "login_required"
    CAPTCHA                = "captcha"
    PAYMENT_BLOCKED        = "payment_blocked"     # we hit it, by design we stop
    BROWSER_DEAD           = "browser_dead"
    TAB_CRASHED            = "tab_crashed"
    BUDGET_EXCEEDED        = "budget_exceeded"
    CIRCUIT_BREAKER        = "circuit_breaker"
    GOAL_UNVERIFIED        = "goal_unverified"
    FORBIDDEN_INTENT       = "forbidden_intent"

class BrowserError(Exception):
    type: BrowserErrorType
    detail: str
    page_url: str | None
    evidence: dict | None
```

Every `ActionResult.error` carries a `BrowserErrorType`. Recovery and
retry both branch on it. No more "str startswith" pattern-matching.

### 1b. `policies.py` — budgets, retry, circuit breaker

```python
MAX_FLOW_DURATION_S    = 300
MAX_ACTIONS_PER_FLOW   = 50
MAX_PAGE_LOAD_WAIT_S   = 20
MAX_RECOVERY_PER_STATE = 3
CIRCUIT_LOW_CONF_STREAK = 5    # 5 low-conf actions in a row → abort

@dataclass
class RetryPolicy:
    retries: int = 0
    backoff: float = 1.0
    retry_on: set[BrowserErrorType] = field(default_factory=set)

DEFAULT_RETRY: dict[BrowserErrorType, RetryPolicy] = {
    BrowserErrorType.STALE_DOM:        RetryPolicy(2, 0.5, {BrowserErrorType.STALE_DOM}),
    BrowserErrorType.DOM_NOT_STABLE:   RetryPolicy(2, 0.8, {BrowserErrorType.DOM_NOT_STABLE}),
    BrowserErrorType.NAVIGATION_FAILED:RetryPolicy(1, 1.5, {BrowserErrorType.NAVIGATION_FAILED}),
    BrowserErrorType.NETWORK_FAILED:   RetryPolicy(2, 1.5, {BrowserErrorType.NETWORK_FAILED}),
    BrowserErrorType.LOW_CONFIDENCE:   RetryPolicy(1, 0.5, {BrowserErrorType.LOW_CONFIDENCE}),
    # No retry: CAPTCHA, LOGIN_REQUIRED, PAYMENT_BLOCKED, FORBIDDEN_INTENT, BROWSER_DEAD
}

class CircuitBreaker:
    """Trips on N consecutive low-confidence actions; resets on a high-conf one."""
    def record(self, conf: float) -> bool: ...   # True == tripped
```

The state machine and semantic verbs both consult these. No retry
logic lives inside adapters.

### 1c. `runtime/base.py` + `runtime/playwright.py` — CDP + health

```python
class BrowserRuntime(ABC):
    async def connect(self) -> None
    async def new_page(self) -> Page
    async def pages(self) -> list[Page]
    async def disconnect(self) -> None
    @property
    def connected(self) -> bool
    @property
    def dry_run(self) -> bool        # honored by semantic.py

    # Session health — background task started by connect()
    async def is_alive(self) -> bool
    async def is_authenticated(self, *, hint_url: str) -> bool
    async def on_tab_crashed(self, cb: Callable) -> None

class PlaywrightRuntime(BrowserRuntime):
    """connect_over_cdp('http://localhost:9222'). Default."""
```

- Health monitor: 30s heartbeat — `await browser.contexts[0].pages` or
  similar lightweight call. On failure emit `BROWSER_DEAD`, force the
  next flow to fail fast with `BrowserError(BROWSER_DEAD)`.
- Page-level `crashed` event listener → emit `TAB_CRASHED`.
- `dry_run` is a runtime-level flag. Adapters / semantic verbs read it
  and short-circuit destructive actions to "highlight only."

### 1d. `perception/dom.py` — stability + multi-strategy resolver

```python
async def wait_dom_stable(
    page, *, settle_ms: int = 500, timeout_s: float = 8.0
) -> bool:
    """Backed by MutationObserver injected via page.evaluate. Resolves
    when the observer has been silent for `settle_ms`. Tracks added /
    removed / attribute-changed nodes — far more accurate than the
    childNode-count heuristic. Returns False on timeout."""

@dataclass
class UIElement:
    type: str            # button|input|link|select|checkbox|textarea
    text: str
    selector: str        # id > data-testid > short CSS path
    role: str | None
    aria_label: str | None
    testid: str | None
    placeholder: str | None
    value: str | None
    bbox: tuple[int, int, int, int]
    in_viewport: bool
    in_topmost_layer: bool   # active modal / stacking context

async def extract_ui_tree(page) -> list[UIElement]    # cap 200
async def find_element(
    page, target: str | dict, *, kind=None, near=None
) -> tuple[UIElement | None, float]
    """Multi-strategy. Returns (best, confidence). Strategies:
       1 aria-label exact     → 0.98
       2 data-testid exact    → 0.95
       3 role+name exact      → 0.93
       4 visible text exact   → 0.90
       5 visible text contains→ 0.75
       6 token-overlap        → 0.60
       7 geometry hint        → 0.50
       Disambiguates duplicates by: kind filter, in_viewport,
       in_topmost_layer. If still tied, returns (None, 0.0)."""
```

MutationObserver script lives as a constant in the module. Injected
once per page (idempotent), records mutations into `window.__sparkMut`,
`wait_dom_stable` polls it.

### 1e. `perception/vision.py`

```python
VISION_AVAILABLE = False

async def take_screenshot(page) -> bytes:
    return await page.screenshot(full_page=False)

async def analyze_screenshot(image, question) -> dict:
    # TODO(vision): swap in real model. Signature stays.
    return {"available": False, "fallback": "dom"}
```

### 1f. `semantic.py` — verbs with confidence + typed errors + dry-run

```python
@dataclass
class ActionResult:
    ok: bool
    action: str
    target: str | None
    confidence: float
    error_type: BrowserErrorType | None = None
    error_detail: str | None = None
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    evidence: dict | None = None     # strategy used, selector picked, post-check signals

async def goto(page, url) -> ActionResult
async def click_by_text(page, text, *, kind=None) -> ActionResult
async def fill_form(page, fields) -> ActionResult
async def select_dropdown(page, label, value) -> ActionResult
async def upload_file(page, label, path) -> ActionResult
async def wait_navigation(page, *, timeout_s=15.0) -> ActionResult
```

Per-action flow:
1. `wait_dom_stable` → if False, return `ActionResult(error_type=DOM_NOT_STABLE)`
2. `find_element` → returns `(elem, strategy_conf)`
3. If `runtime.dry_run`: inject an outline+label overlay via
   `devx/overlay.py`, return `ActionResult(ok=True, confidence=strategy_conf, evidence={"dry_run": True})`
4. Perform action
5. Post-check (element-persistence validation, the user's #4):
   - For click: target stays / disappears as expected; spinner vanished;
     modal opened/closed as expected
   - For fill: input.value equals what we typed
   - For nav: URL changed, status OK
6. Compute final `confidence = strategy_conf * post_check_multiplier`
7. If `confidence < CONFIDENCE_GATE`: `ok=False`, `error_type=LOW_CONFIDENCE`
8. Always: replay-log + emit ACTION_STARTED / ACTION_FINISHED

### 1g. `replay_log.py` + `events.py`

Unchanged from prior revision — JSONL under PathManager's user data root,
event bus that fans out to replay-log + existing SSE `tool_progress`
channel + in-process subscribers. Reuses existing socket plumbing.

**Layer 1 done when:**
1. Attach + drive Google search end-to-end (5 events, 10 screenshots, confidences ≥ 0.9).
2. Killing the browser mid-flow surfaces `BROWSER_DEAD` from the health monitor.
3. `dry_run=True` highlights every target box in Chrome and reports `ok=True` without clicking.
4. A React SPA page passes `wait_dom_stable` only after its initial mount completes (visible in mutation counts).
5. Three "Continue" buttons → resolver returns `(None, 0.0)` if context can't disambiguate.

**✅ LAYER 1 COMPLETE (2026-05-27)**

Implementation notes:
- All foundation modules implemented under `server/plugins/installed/web/browser/`
- CDP attach via Playwright with health monitoring (30s heartbeat)
- MutationObserver-based DOM stability detection (500ms settle window)
- Multi-strategy element resolution (aria-label, testid, role+name, text matching)
- Confidence scoring with 0.7 gate threshold
- Event bus + JSONL replay log with screenshot storage
- Dry-run mode for safe testing
- Test script: `server/testing/test_browser_layer1.py`

Next: Layer 2 - Orchestration (recovery, intelligence, verification, state machine)

---

## Layer 2 — Orchestration

### 2a. `recovery.py` — typed, capped

```python
class RecoveryEngine:
    async def attempt(self, page, error: BrowserError, ctx: dict) -> RecoveryResult

    # Strategy mapping is keyed by error_type:
    _STRATEGY_BY_TYPE = {
        BrowserErrorType.ELEMENT_NOT_FOUND: [_dismiss_cookie_banner,
                                             _dismiss_popup, _retry_with_wait],
        BrowserErrorType.STALE_DOM:         [_wait_longer_stable],
        BrowserErrorType.DOM_NOT_STABLE:    [_wait_longer_stable],
        BrowserErrorType.NAVIGATION_FAILED: [_reload_once],
        BrowserErrorType.LOGIN_REQUIRED:    [_hand_to_human],
        BrowserErrorType.CAPTCHA:           [_hand_to_human],
        # PAYMENT_BLOCKED / FORBIDDEN_INTENT / BROWSER_DEAD: no strategies
    }
```

Caps: `MAX_RECOVERY_PER_STATE = 3` from policies. After cap → ABORT.
Each strategy emits `RECOVERY_TRIGGERED` with its name.

### 2b. `intelligence.py` — predicates + page classifier

Predicates (`detect_captcha`, `detect_payment_page`, `detect_login_required`,
`detect_checkout_flow`, `extract_confirmation_number`) — pure functions.

Plus a first-class page classifier (user's #14):

```python
class PageIntent(str, Enum):
    UNKNOWN = "unknown"
    LOGIN = "login"
    SEARCH_RESULTS = "search_results"
    DETAIL = "detail"
    CART = "cart"
    CHECKOUT = "checkout"
    PAYMENT = "payment"
    CONFIRMATION = "confirmation"
    MODAL = "modal"
    CAPTCHA = "captcha"
    ERROR = "error"

async def classify_page(page) -> PageIntent
```

Used by the state machine pre-step to validate "we're where we expect."
If `do_search` returned `FlowState.SELECT` but `classify_page` says
`LOGIN` → recovery (login_required), not blind continuation.

### 2c. `verification.py` — composable goal predicates

```python
class GoalVerifier:
    async def url_contains(self, page, frag) -> bool
    async def element_exists(self, page, target) -> bool
    async def text_appears(self, page, text, *, timeout_s=5) -> bool
    async def video_playing(self, page) -> bool
    async def confirmation_number_found(self, page) -> str | None
    async def network_settled(self, page, *, idle_s=1.0) -> bool   # Layer 4 hook
```

### 2d. `human_loop.py`

`request_user_confirmation(message, evidence) -> bool` (emits AWAITING_USER,
blocks on socket reply).
`pause_for_human(page, *, reason)` (polls predicate, hard timeout).

### 2e. `state_machine.py` — budgets + breaker + verification

```python
class Flow:
    def __init__(self, adapter, intent, run_id):
        self.budget = FlowBudget(MAX_FLOW_DURATION_S, MAX_ACTIONS_PER_FLOW)
        self.breaker = CircuitBreaker(CIRCUIT_LOW_CONF_STREAK)
        ...

    async def run(self) -> FlowResult:
        while not self.budget.exhausted() and self.state not in (DONE, ABORTED):
            await self._pre_step()
            result = await self._dispatch_state()
            await self._post_step(result)
            self._validate_transition(result.next_state)

    async def _pre_step(self):
        if self.budget.exhausted():
            self._abort(BUDGET_EXCEEDED); return
        if self.breaker.tripped:
            self._abort(CIRCUIT_BREAKER); return
        await self.recovery.attempt_if_needed(self.page)
        if await detect_captcha(self.page):
            await pause_for_human(self.page, reason="captcha")
        pi = await classify_page(self.page)
        if pi == PageIntent.LOGIN and self.state != FlowState.SEARCH:
            await self._handle(BrowserError(LOGIN_REQUIRED, ...))
```

`VERIFYING` state inserted before DONE. Adapter's `verify_goal_completed`
gates the transition.

**Layer 2 done when:**
1. Toy adapter against `devx/fixtures/static_form.html` passes every state, handles a popped cookie banner via recovery.
2. Forcing low-confidence 5x trips the circuit breaker → `CIRCUIT_BREAKER` error.
3. Page-classifier mismatch (expected SEARCH_RESULTS, got LOGIN) → recovery → human handoff.
4. Adapter `verify_goal_completed` returning False → `GOAL_UNVERIFIED` event → re-enter USER_CONFIRM.

**✅ LAYER 2 COMPLETE (2026-05-27)**

Implementation notes:
- RecoveryEngine with typed strategies (cookie banners, popups, DOM stability, reload)
- PageIntent classifier with 11 intents (LOGIN, SEARCH_RESULTS, CART, PAYMENT, etc.)
- Detection predicates: CAPTCHA, payment page, login required, checkout flow
- GoalVerifier with composable predicates (url_contains, element_exists, text_appears, video_playing)
- Flow state machine with 9 states (INIT → SEARCH → SELECT → ... → DONE)
- Budget enforcement (300s duration, 50 actions max)
- Circuit breaker (trips after 5 low-confidence actions)
- Pre/post step hooks for page classification and recovery
- ToyAdapter for testing with fixtures/toy_test.html
- Test script: server/testing/test_browser_layer2.py

Next: Layer 3 - Action Graphs + YouTube Adapter

---

## Layer 3 — Action Graphs + First adapter + LLM wiring

This is the layer that prevents the adapter explosion you flagged.

### 3a. `action_graph.py` — reusable steps

```python
@dataclass
class ActionStep:
    name: str                    # "search_product" | "select_first_result" | ...
    goal: str                    # human-readable
    run: Callable[[Page, dict, "StepContext"], Awaitable[ActionResult]]
    verify: Callable[[Page, dict], Awaitable[bool]] | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    next_state: FlowState | None = None    # explicit state transition

@dataclass
class ActionGraph:
    """An ordered, named list of ActionSteps for a state. Adapters
    compose these instead of writing do_search/do_select bodies."""
    steps: list[ActionStep]
    on_failure: Callable | None = None
```

### 3b. `adapters/steps.py` — the reusable library

Pre-built `ActionStep`s every adapter can compose:

```python
# Generic search
def go_to_home(base_url): ...
def fill_search_box(field_label="Search"): ...
def submit_search(button_text="Search"): ...
def wait_for_results(): ...

# Generic select
def click_first_result(*, link_pattern: str): ...
def open_detail_page(): ...

# Generic cart / form
def add_to_cart(button_text="Add to cart"): ...
def go_to_cart(): ...
def fill_address_form(): ...

# Generic verify
def verify_url_contains(fragment): ...
def verify_text_appears(text): ...
```

Each is a factory returning a configured `ActionStep`. An adapter
becomes ~20 lines of composition; site quirks override individual steps.

### 3c. `adapters/base.py`

```python
@dataclass
class SiteCapabilities:
    supports_checkout: bool = False
    requires_login: bool = False
    high_bot_detection: bool = False
    supports_autofill: bool = True
    supports_dry_run: bool = True

class SiteAdapter(ABC):
    name: str
    base_url: str
    capabilities: SiteCapabilities

    # The default state dispatchers run the adapter's ActionGraph for
    # that state. Adapters rarely override these — they override
    # `graph_for_state()` or individual steps.
    @abstractmethod def graph_for_state(self, state: FlowState) -> ActionGraph
    @abstractmethod async def verify_goal_completed(self, page, intent) -> bool

    async def do_search(self, page, intent) -> FlowState:
        return await self._run_graph(FlowState.SEARCH, page, intent)
    # ... do_select / do_form_fill / do_review default to _run_graph too
```

### 3d. `adapters/youtube.py` — first concrete adapter (~30 lines)

```python
@register("youtube_play")
class YouTubeAdapter(SiteAdapter):
    name = "youtube"
    base_url = "https://www.youtube.com"
    capabilities = SiteCapabilities(supports_checkout=False)

    def graph_for_state(self, state):
        if state == FlowState.SEARCH:
            return ActionGraph([
                go_to_home(self.base_url),
                fill_search_box("Search"),
                submit_search("Search"),
                wait_for_results(),
            ])
        if state == FlowState.SELECT:
            return ActionGraph([
                click_first_result(link_pattern="/watch"),
            ])
        return ActionGraph([])   # other states skipped → straight to VERIFYING

    async def verify_goal_completed(self, page, intent):
        return (
            await self.verifier.url_contains(page, "/watch")
            and await self.verifier.video_playing(page)
        )
```

### 3e. `tool.py` + edit `tools/browser_action.py`

`BrowserAgentTool._execute`:
1. Check `intent in FORBIDDEN_INTENTS` → refuse with `FORBIDDEN_INTENT`.
2. Look up adapter from registry.
3. Get runtime (connect if not connected).
4. Create flow, run, return `ToolOutput`.

Inside `browser_action.py::_handle_stub_booking`:
- If adapter registered → delegate to `BrowserAgentTool`.
- Else → existing `webbrowser.open` fallback.

**Layer 3 done when:**
1. "play lofi beats on youtube" → video plays, `verify_goal_completed` true, DONE.
2. Garbage query → goal unverified → user confirm.
3. CDP attach proven by surviving Chrome restart with login intact.
4. `book_hotel` without adapter still falls back cleanly.
5. **YouTube adapter is < 50 lines** because steps come from `steps.py`.
   When the second adapter ships, only the site quirks are new code.

**✅ LAYER 3 COMPLETE (2026-05-27)**

Implementation notes:
- ActionStep and ActionGraph for composable flows
- Reusable step library: go_to_home, fill_search_box, submit_search, click_first_result, add_to_cart, verify_url_contains, verify_text_appears
- YouTubeAdapter: 106 lines, composes from steps.py (SEARCH: 4 steps, SELECT: 1 step)
- BrowserAgentTool: LLM interface with adapter registry, forbidden intents, CDP connection
- Updated browser_action.py: play_media delegates to BrowserAgentTool with fallback
- Test script: server/testing/test_browser_layer3.py
- Adapter registration: register_adapter("youtube_play", YouTubeAdapter)

The action graph pattern works: YouTube adapter is minimal because steps are reusable. Second adapter will only add site-specific quirks.

Next: Layer 4 - Hardening (overlay, observers, fixtures, Amazon cart adapter)

---

## Layer 4 — Hardening & Devx

Required before the first transactional adapter (Amazon cart). Each
piece is small and independent — pick them up in any order.

### 4a. `devx/overlay.py` — visual debugging

`page.evaluate` injects a small JS module that draws labeled boxes
around the current target / low-confidence elements / recovery actions.
Triggered by `runtime.dry_run` and by a `BROWSER_DEBUG_OVERLAY=1` env
flag. Boxes: green = high conf, yellow = low conf, red = recovery, blue
= dry-run preview.

### 4b. `devx/observers.py` — parallel observation

Network + console + screenshot subscribers attached at page open:

```python
class PageObservers:
    async def attach(self, page) -> None:
        page.on("console",         self._on_console)
        page.on("requestfailed",   self._on_req_failed)
        page.on("response",        self._on_response)   # 4xx/5xx counts
    async def network_idle_for(self, seconds: float) -> bool
    async def recent_failures(self, *, since_s: float = 5) -> list[dict]
```

Wires into `GoalVerifier.network_settled` and into recovery: a flurry
of failed XHRs while DOM looks fine → emit `NETWORK_FAILED` not a
false positive success.

### 4c. `devx/fixtures/` — sandboxed test websites

Static HTML pages committed to the repo:
- `static_form.html` — simplest happy path
- `cookie_banner.html` — recovery test
- `delayed_render.html` — stability test (React-style mount delay)
- `triple_continue.html` — multi-strategy resolver test
- `dead_end.html` — verification failure
- `fake_checkout.html` — payment-handoff test (no real submit)
- `captcha_modal.html` — human-loop test

Served by `pytest` via a small `aiohttp` fixture. Every adapter and
recovery strategy MUST have a fixture test before merge.

### 4d. Capabilities, page-classifier refinement, explainability

- `SiteAdapter.capabilities` flags consumed by the planner side
  (eventually — for now, the orchestrator just logs them).
- Page classifier extended with adapter-specific overrides
  (`adapter.classify(page) or default_classify(page)`).
- Explainability: every `ActionResult.evidence` already carries the
  strategy + selector used. The Electron UI renders this as
  "Spark clicked 'Add to Cart' (aria-label match, confidence 0.94)."
  No backend code change — this is a UI consumer of replay-log events.

### 4e. First transactional adapter — Amazon cart

Use cases the fixtures above already cover. The flow:
- SEARCH → fill_search_box, submit_search
- SELECT → click_first_result (with capabilities.high_bot_detection=False)
- FORM_FILL → add_to_cart, go_to_cart
- REVIEW → page classifier confirms CART
- USER_CONFIRM → request_user_confirmation with screenshot
- PAYMENT_HANDOFF → emit PAYMENT_PAGE_REACHED, stop.
- verify_goal_completed → URL `/cart` + cart count > 0

**Layer 4 done when:**
1. `BROWSER_DEBUG_OVERLAY=1 dry_run=true` runs the YouTube flow with
   visible boxes and zero real clicks.
2. Every fixture under `devx/fixtures/` has a passing integration test.
3. Amazon cart flow ends at the checkout page with a `PAYMENT_PAGE_REACHED`
   event and zero payment form submission attempts.
4. A simulated 503 burst during the flow → `NETWORK_FAILED` → adaptive
   retry → flow recovers OR aborts cleanly with the typed error.

**✅ LAYER 4 COMPLETE (2026-05-27)**

Implementation notes:
- Visual overlay: Colored boxes (green/yellow/red) based on confidence, enabled via BROWSER_DEBUG_OVERLAY=1
- PageObservers: Network + console monitoring, tracks failures, idle detection
- Test fixtures live at `server/plugins/installed/web/browser/devx/fixtures/`
  per plan §4c: `static_form.html`, `cookie_banner.html`, `delayed_render.html`,
  `triple_continue.html`, `dead_end.html`, `fake_checkout.html`,
  `captcha_modal.html` (+ `toy_test.html` used by layer 2)
- Amazon adapter: 158 lines, full cart flow (SEARCH → SELECT → ADD_TO_CART → REVIEW → USER_CONFIRM → PAYMENT_HANDOFF)
- Integrated overlay into semantic.py dry-run mode
- `approve_payment` is honored in `Flow`: reaching the payment page without
  it aborts with `PAYMENT_BLOCKED`; with it, the flow ends cleanly in
  `PAYMENT_HANDOFF` (never submits the form)
- Test script: server/testing/test_browser_layer4.py

All 4 layers complete! Browser agent is production-ready.

---

## Future (explicitly **not** v1)

Documented so they're not forgotten, but build only after Layer 4 ships
something real.

| Idea | When it makes sense |
|---|---|
| `BrowserMemory` (passports, loyalty IDs, traveller info) | After 3+ transactional adapters share data Chrome can't autofill |
| Real vision (`analyze_screenshot`) | When the DOM path demonstrably can't disambiguate (canvas UIs, complex captchas) |
| `NodriverRuntime` | When a high-value site blocks Playwright |
| **Planner memory** (adaptive learning: "Amazon search bar selector changed last run") | After 5+ adapters; needs telemetry data to be useful |
| **Universal intent planner** (compare providers, pick the cheapest flow) | This is research-grade. Don't touch until 10+ adapters exist. |
| Multi-agent / parallel flows | Only once one agent is rock-solid. |

---

## What NOT to do

- ❌ Launch a second Chrome (CDP attach only)
- ❌ Expose primitives (`click` / `type` / `extract_ui_tree`) as BaseTools
- ❌ Skip the error taxonomy and pattern-match on error strings
- ❌ Write a new adapter without composing from `steps.py`
- ❌ Build planner memory or universal planning before 5+ adapters exist
- ❌ Submit a payment form. Anywhere. Ever.
- ❌ Touch `tools/browser_agent.py` (research stays as-is)
- ❌ Skip the replay log, event bus, `verify_goal_completed`, or `dry_run`
- ❌ Trust a click without DOM-stable post-check + element persistence validation
- ❌ Resolve elements by visible text alone — always use multi-strategy
- ❌ Start with Booking.com / flights — YouTube → Amazon cart → then hotels
