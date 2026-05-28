You are building the correct thing.
Most AI agents fail because they start from “LLM automation.”
You should start from:

deterministic browser infrastructure + recovery systems + state management

The LLM is only the planner.

Your architecture should look like this:

The Real Architecture of Spark Actions
User Intent
    ↓
Planner Agent (LLM)
    ↓
Action Graph / State Machine
    ↓
Browser Runtime Layer
    ↓
Site Adapters
    ↓
Human Approval Layer
    ↓
Payment Hand-off

The mistake most people make:

LLM → click buttons randomly

That becomes unstable instantly.

STEP 1 — DO NOT BUILD SITE TOOLS FIRST

Do NOT start with:

book_hotel
book_flight
buy_product

Wrong order.

First build:

Spark Browser Runtime

Everything depends on this.

STEP 2 — Best Browser Stack (2026)

You have 3 real options.

Stack	Good?	Problem
Selenium	Old	Too detectable
Playwright	VERY GOOD	Best overall
Nodriver	Good stealth	Harder infra
Pure CDP	Powerful	Too low-level
Use This
Core Stack
Playwright + connect_over_cdp()

Why:

stable
fast
modern
stealth capable
supports existing Chrome sessions
supports screenshots
supports multi-tabs
supports downloads
supports iframes
supports shadow DOM
easiest debugging

This is the industry answer now.

Even OpenAI Operator-like systems use CDP/browser control internally.

STEP 3 — MOST IMPORTANT PART
Attach To User’s REAL Chrome

This is the breakthrough.

Without this:

no saved logins
no carts
no sessions
CAPTCHA hell
constant OTPs

You need:

Chrome Remote Debugging

User launches Chrome like this:

Windows:

chrome.exe --remote-debugging-port=9222

Mac:

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

Then Spark connects:

browser = playwright.chromium.connect_over_cdp(
    "http://localhost:9222"
)

Now Spark gets:

existing cookies
existing logins
existing sessions
Gmail logged in
Booking.com logged in
Amazon logged in

This changes everything.

STEP 4 — YOUR FIRST REAL TOOLS

Do NOT expose primitive tools directly to LLM.

Bad:

browser_click
browser_fill
browser_wait

The LLM becomes unstable.

Instead:

Build Semantic Tools

Example:

click_by_text("Continue")
fill_form({
  "email": "...",
  "checkin": "...",
})
select_date_range()
wait_navigation()
extract_interactive_elements()

These internally use Playwright.

The LLM should operate at semantic level.

STEP 5 — CRITICAL: DOM EXTRACTION

This is where most agents fail.

You CANNOT dump full HTML into the LLM.

Terrible idea.

Instead build:

Interactive Accessibility Tree Extractor

Extract ONLY:

buttons
inputs
dropdowns
labels
forms
clickable regions
visible text
aria labels

Basically:

[
  {
    "type": "button",
    "text": "Continue",
    "selector": "#submit-btn"
  }
]

This massively improves reasoning.

STEP 6 — YOU NEED VISUAL MODE TOO

DOM alone is not enough.

Modern sites:

canvas UIs
shadow DOM
dynamic React
invisible overlays
weird CSS

So Spark needs:

Dual Perception
1. Structured DOM mode

Fast.

2. Screenshot Vision mode

Fallback.

Workflow:

DOM parse succeeds?
    YES → continue
    NO  → vision model checks screenshot

This is how advanced agents work.

STEP 7 — THE MOST IMPORTANT CONCEPT
State Machines

DO NOT make Spark “freestyle.”

Every flow should be:

SEARCH
→ SELECT
→ FORM_FILL
→ REVIEW
→ USER_CONFIRM
→ PAYMENT_HANDOFF
→ CONFIRMATION_CAPTURE

This is absolutely critical.

Without state machines:

loops
hallucinated clicks
repeated actions
accidental purchases
STEP 8 — PAYMENT RULE

Correct approach:

Spark NEVER presses final payment confirmation

Instead:

Spark reaches payment page
→ freezes
→ asks user to complete payment
→ resumes after redirect

This avoids:

legal problems
trust issues
accidental purchases
payment compliance nightmares

Very important.

STEP 9 — YOUR FIRST SUPPORTED SITES

Do NOT start with flights.

Flights are hell.

Start in this order:

Phase 1
EASY
YouTube
Netflix
Google Maps
Amazon search/cart
Food delivery search

Goal:
learn browser runtime.

Phase 2
MEDIUM
Booking.com
Airbnb
Zomato
OpenTable

Goal:
form automation.

Phase 3
HARD
Flight booking
Seat selection
Ticket systems
Visa forms

These require much more robustness.

STEP 10 — YOU NEED SITE ADAPTERS

Do NOT rely purely on LLM reasoning.

Instead:

class BookingDotComAdapter:
    def search_hotels()
    def select_room()
    def fill_guest_info()

Because websites are semi-stable.

Adapters dramatically improve reliability.

Hybrid system:

Site adapter first
LLM fallback second

This is the correct architecture.

STEP 11 — CAPTCHA STRATEGY

Reality:

You will NOT bypass CAPTCHA reliably.

Correct strategy:

CAPTCHA detected
→ pause automation
→ ask user to solve
→ continue afterward

That is what real production systems do.

STEP 12 — MEMORY SYSTEM

You need local encrypted memory.

Store
addresses
passenger names
preferences
loyalty IDs

But NOT payment cards.

Never.

STEP 13 — OBSERVABILITY (VERY IMPORTANT)

You need full replay logs.

Every action:

{
  "timestamp": "...",
  "action": "click",
  "target": "Continue",
  "screenshot": "..."
}

This is mandatory for debugging.

Without this you cannot scale.

STEP 14 — REAL TOOL LIST YOU SHOULD BUILD
Core Runtime
connect_browser
open_tab
navigate
extract_ui_tree
click
type
select_dropdown
upload_file
wait_for_navigation
take_screenshot
Intelligence Layer
detect_checkout_flow
detect_login_required
detect_captcha
detect_payment_page
extract_confirmation_number
Human Safety Layer
request_user_confirmation
pause_for_human
resume_after_human
Session Layer
save_session
restore_session
vault_credentials
profile_autofill
STEP 15 — BEST MODELS FOR THIS

You need 2 models.

Planner Model

Cheap + fast.

Examples:

Google Gemini 2.5 Flash
OpenAI GPT-5 mini
DeepSeek DeepSeek V4
Vision Recovery Model

More expensive.

Examples:

GPT-5.5
Claude Opus
Gemini Pro Vision

Used only when DOM reasoning fails.

STEP 16 — YOUR BIGGEST ENGINEERING CHALLENGE

Not browser control.

Not AI.

Recovery.

Real websites fail constantly:

popups
cookie banners
session expiry
modal dialogs
lazy loading
A/B testing
localization

Your agent quality depends on:

Can it recover automatically?

That is the real moat.