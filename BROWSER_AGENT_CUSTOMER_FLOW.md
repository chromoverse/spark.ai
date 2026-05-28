# Browser Agent - Customer Consumption Flow

## 🎯 How Customers Use It

### Flow 1: Via LLM Chat (Primary)
```
Customer → Chat Message → LLM → BrowserAgentTool → Browser Action
```

**Example:**
```
Customer: "Play lofi beats on YouTube"
    ↓
LLM detects intent: youtube_play
    ↓
Calls: browser_agent(intent="youtube_play", query="lofi beats")
    ↓
BrowserAgentTool executes flow
    ↓
Customer sees: "✓ Playing lofi beats on YouTube"
```

**Code Path:**
1. User message → LLM tool selection
2. LLM calls `BrowserAgentTool._execute()`
3. Tool looks up adapter: `youtube_play` → `YouTubeAdapter`
4. Creates Flow with adapter
5. Flow runs state machine: INIT → SEARCH → SELECT → VERIFY → DONE
6. Returns result to LLM
7. LLM formats response to user

---

### Flow 2: Via Existing browser_action.py (Fallback)
```
Customer → Chat → LLM → browser_action → Delegates to BrowserAgentTool
```

**Example:**
```
Customer: "Play that video"
    ↓
LLM calls: browser_action(action="play_media", title="that video")
    ↓
browser_action._handle_play_media() tries BrowserAgentTool
    ↓
If automation works: Returns automated result
If automation fails: Falls back to webbrowser.open()
```

**Code Path:**
1. LLM calls existing `BrowserActionTool`
2. Handler `_handle_play_media()` tries `BrowserAgentTool` first
3. On success: Returns automated result
4. On failure: Falls back to URL open (backward compatible)

---

## 🔄 How New Changes Propagate

### Adding a New Adapter (e.g., Booking.com)

**Step 1: Create Adapter** (10-20 lines)
```python
# server/plugins/installed/web/browser/adapters/booking.py
from .base import SiteAdapter
from .steps import go_to_home, fill_search_box, submit_search, click_first_result

class BookingAdapter(SiteAdapter):
    name = "booking"
    base_url = "https://www.booking.com"
    
    def graph_for_state(self, state):
        if state == FlowState.SEARCH:
            return ActionGraph([
                go_to_home(self.base_url),
                fill_search_box("Where are you going?"),
                submit_search("Search"),
            ])
        # ... other states
    
    async def verify_goal_completed(self, page, intent, ctx, runtime):
        return await self.verifier.url_contains(page, "/hotel/")
```

**Step 2: Register Adapter** (1 line)
```python
# server/plugins/installed/web/browser/tool.py
from .adapters.booking import BookingAdapter
register_adapter("book_hotel", BookingAdapter)
```

**Step 3: Customer Uses It** (Immediately!)
```
Customer: "Book a hotel in Paris"
    ↓
LLM: browser_agent(intent="book_hotel", query="Paris")
    ↓
Works automatically! No restart needed.
```

---

### Adding a New Reusable Step

**Step 1: Add to steps.py** (5-10 lines)
```python
# server/plugins/installed/web/browser/adapters/steps.py
def select_date(date_label: str) -> ActionStep:
    async def run(ctx: StepContext):
        return await click_by_text(ctx.page, date_label, ctx.runtime)
    return ActionStep(name="select_date", goal=f"Select {date_label}", run=run)
```

**Step 2: Use in Any Adapter**
```python
# Any adapter can now use it
ActionGraph([
    fill_search_box("Destination"),
    select_date("Check-in"),  # New step!
    submit_search("Search"),
])
```

**Step 3: All Adapters Benefit**
- YouTube adapter: No change needed
- Amazon adapter: No change needed
- Booking adapter: Can use new step immediately

---

### Improving Core Functionality (e.g., Better Element Resolution)

**Step 1: Update perception/dom.py**
```python
# Add new strategy to find_element()
# Strategy 7: CSS class matching → 0.55 confidence
elif target_lower in el.selector.lower():
    conf = 0.55
```

**Step 2: All Adapters Benefit Automatically**
- No adapter changes needed
- All flows get better element finding
- Confidence scores improve across the board

---

## 📦 Deployment Flow

### Development → Production

```
1. Developer adds/modifies adapter
   ↓
2. Commits to git
   ↓
3. CI/CD runs tests:
   - test_browser_layer1.py (foundation)
   - test_browser_layer2.py (orchestration)
   - test_browser_layer3.py (adapters)
   - test_browser_layer4.py (hardening)
   ↓
4. Tests pass → Deploy to production
   ↓
5. Server restarts (or hot-reload if supported)
   ↓
6. Customers immediately have new adapter
```

### No Customer Action Required
- No app updates
- No configuration changes
- No manual setup
- Just works™

---

## 🎭 Customer Experience Examples

### Example 1: YouTube (Already Works)
```
Customer: "Play lofi hip hop beats"
Assistant: "Playing lofi hip hop beats on YouTube..."
[Video starts playing in customer's browser]
Customer: "Thanks!"
```

### Example 2: Amazon (After Adapter Added)
```
Customer: "Add wireless mouse to my cart"
Assistant: "Adding wireless mouse to your Amazon cart..."
[Item appears in cart]
Assistant: "Added! Ready to checkout?"
Customer: "Yes"
[Browser opens to checkout page]
```

### Example 3: Booking.com (Future)
```
Customer: "Book a hotel in Paris for next week"
Assistant: "Searching hotels in Paris..."
[Browser shows search results]
Assistant: "Found 50 hotels. Which one?"
Customer: "The one with best reviews"
[Browser opens hotel page]
Assistant: "Ready to book?"
```

---

## 🔧 Maintenance Flow

### When a Site Changes (e.g., YouTube redesign)

**Option 1: Adapter Still Works** (90% of cases)
- Multi-strategy element resolution adapts
- No changes needed
- Customers don't notice

**Option 2: Adapter Needs Update** (10% of cases)
```python
# Update YouTube adapter
def graph_for_state(self, state):
    if state == FlowState.SEARCH:
        return ActionGraph([
            go_to_home(self.base_url),
            fill_search_box("Search"),  # Changed from "Search" to "search"
            submit_search("Search"),
        ])
```
- Deploy update
- Customers get fix automatically

---

## 📊 Customer Visibility

### What Customers See

**Success:**
```
✓ Playing lofi beats on YouTube
✓ Added wireless mouse to cart
✓ Hotel search complete
```

**Dry-Run Mode:**
```
[DRY-RUN] Would click "Search" button (confidence: 0.95)
[DRY-RUN] Would fill "Email" field
[DRY-RUN] Would navigate to checkout
```

**Errors (Graceful):**
```
⚠ Couldn't find "Add to Cart" button. Opening product page for you.
[Falls back to URL open]
```

**Human Needed:**
```
⏸ Please complete the CAPTCHA
⏸ Please log in to continue
⏸ Ready to proceed to payment? (Yes/No)
```

---

## 🚀 Scaling Flow

### Adding More Adapters

**Current: 3 adapters**
- YouTube (106 lines)
- Amazon (158 lines)
- Toy (test)

**Future: 10+ adapters**
- Booking.com (hotels)
- OpenTable (restaurants)
- Ticketmaster (events)
- Netflix (streaming)
- Spotify (music)
- Uber (rides)
- DoorDash (food)
- etc.

**Key Insight:**
- Each new adapter: 50-150 lines
- Reuses steps.py library
- No changes to existing adapters
- No changes to core framework
- Customers get new capabilities automatically

---

## 💡 Key Takeaways

### For Customers:
1. **Zero setup** - Just works with their existing browser
2. **Zero maintenance** - Updates happen automatically
3. **Graceful fallback** - If automation fails, opens URL
4. **Human-in-loop** - Asks for help when needed (CAPTCHA, login, payment)

### For Developers:
1. **Add adapter** - 50-150 lines, register, done
2. **Reuse steps** - Library of 12+ reusable steps
3. **No breaking changes** - New adapters don't affect old ones
4. **Test coverage** - 4 test scripts validate everything

### For Product:
1. **Fast iteration** - New site support in hours, not weeks
2. **Reliable** - Typed errors, recovery, circuit breaker
3. **Observable** - Event bus, replay logs, visual overlay
4. **Safe** - Dry-run mode, payment handoff, forbidden intents

---

## 🎯 Bottom Line

**Customer Flow:**
```
Customer types message → LLM picks tool → Adapter executes → Customer sees result
```

**Change Flow:**
```
Developer adds adapter → Commits → Tests pass → Deploy → Customers use it
```

**No customer action required. Just works.** ✨
