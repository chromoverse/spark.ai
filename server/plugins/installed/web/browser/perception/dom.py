"""DOM stability and element resolution."""
import asyncio
from dataclasses import dataclass
from typing import Optional, Any

# MutationObserver script injected into page
MUTATION_OBSERVER_SCRIPT = """
(() => {
  if (window.__sparkMut) return;
  window.__sparkMut = { count: 0, lastChange: Date.now() };
  const obs = new MutationObserver(() => {
    window.__sparkMut.count++;
    window.__sparkMut.lastChange = Date.now();
  });
  obs.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeOldValue: false,
    characterData: true
  });
})();
"""


@dataclass
class UIElement:
    type: str
    text: str
    selector: str
    role: Optional[str] = None
    aria_label: Optional[str] = None
    testid: Optional[str] = None
    placeholder: Optional[str] = None
    value: Optional[str] = None
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    in_viewport: bool = False
    in_topmost_layer: bool = False
    href: Optional[str] = None


async def wait_dom_stable(page: Any, *, settle_ms: int = 500, timeout_s: float = 8.0) -> bool:
    """Wait for DOM to stabilize using MutationObserver."""
    try:
        await page.evaluate(MUTATION_OBSERVER_SCRIPT)
        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout_s:
            result = await page.evaluate("() => window.__sparkMut")
            if not result:
                await asyncio.sleep(0.1)
                continue
            elapsed = await page.evaluate("() => Date.now() - window.__sparkMut.lastChange")
            if elapsed >= settle_ms:
                return True
            await asyncio.sleep(0.1)
        return False
    except Exception:
        return False


async def extract_ui_tree(page: Any) -> list[UIElement]:
    """Extract interactive elements from page (cap 200)."""
    script = """
    () => {
      const elements = [];
      const selectors = 'button, a, input, select, textarea, [role="button"], [role="link"]';
      const nodes = document.querySelectorAll(selectors);
      for (let i = 0; i < Math.min(nodes.length, 200); i++) {
        const el = nodes[i];
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const id = el.id;
        const testid = el.getAttribute('data-testid');
        const name = el.getAttribute('name');
        let selector = '';
        if (id) selector = `#${CSS.escape(id)}`;
        else if (testid) selector = `[data-testid="${testid}"]`;
        else if (name && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
          selector = `${el.tagName.toLowerCase()}[name="${name}"]`;
        }
        elements.push({
          type: el.tagName.toLowerCase(),
          text: (el.textContent || '').trim().slice(0, 100),
          selector: selector,
          role: el.getAttribute('role'),
          aria_label: el.getAttribute('aria-label'),
          testid: testid,
          placeholder: el.getAttribute('placeholder'),
          value: el.value || null,
          bbox: [rect.left, rect.top, rect.width, rect.height],
          in_viewport: rect.top >= 0 && rect.left >= 0 && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth,
          in_topmost_layer: el.closest('dialog, [role="dialog"]') !== null,
          href: el.tagName === 'A' ? (el.getAttribute('href') || null) : null
        });
      }
      return elements;
    }
    """
    try:
        raw = await page.evaluate(script)
        return [UIElement(**e) for e in raw]
    except Exception:
        return []


async def find_element(
    page: Any,
    target: str | dict,
    *,
    kind: Optional[str] = None,
    near: Optional[str] = None
) -> tuple[Optional[UIElement], float]:
    """Multi-strategy element finder. Returns (element, confidence)."""
    elements = await extract_ui_tree(page)
    if not elements:
        return None, 0.0

    target_text = target if isinstance(target, str) else target.get("text", "")
    target_lower = target_text.lower()

    candidates = []
    for el in elements:
        if kind and el.type != kind:
            continue
        
        conf = 0.0
        # Strategy 1: aria-label exact
        if el.aria_label and el.aria_label.lower() == target_lower:
            conf = 0.98
        # Strategy 2: testid exact
        elif el.testid and el.testid.lower() == target_lower:
            conf = 0.95
        # Strategy 3: role+name exact
        elif el.role and el.text.lower() == target_lower:
            conf = 0.93
        # Strategy 4: visible text exact
        elif el.text.lower() == target_lower:
            conf = 0.90
        # Strategy 4b: placeholder exact (inputs rarely carry visible text;
        # their placeholder is the user-visible label). Required for sites
        # like YouTube whose search box has no aria-label / id / testid.
        elif el.placeholder and el.placeholder.lower() == target_lower:
            conf = 0.88
        # Strategy 5: visible text contains
        elif target_lower in el.text.lower():
            conf = 0.75
        # Strategy 5b: placeholder contains
        elif el.placeholder and target_lower in el.placeholder.lower():
            conf = 0.70
        # Strategy 6: token overlap
        elif any(token in el.text.lower() for token in target_lower.split() if len(token) > 2):
            conf = 0.60
        
        if conf > 0:
            # Tiebreaker boosts. Viewport is a *decisive* signal — when
            # a page renders two copies of the same labeled element
            # (mobile + desktop, e.g. YouTube's search bar), only one is
            # actually clickable. The boost needs to exceed the ambiguity
            # threshold below or find_element will refuse to pick.
            if el.in_viewport:
                conf += 0.15
            if el.in_topmost_layer:
                conf += 0.05
            candidates.append((el, min(conf, 1.0)))

    if not candidates:
        return None, 0.0

    candidates.sort(key=lambda x: x[1], reverse=True)

    # Genuine ambiguity: two candidates close in score AND with the same
    # viewport/layer disposition (we can't pick one over the other).
    if len(candidates) > 1:
        top, second = candidates[0], candidates[1]
        same_viewport = top[0].in_viewport == second[0].in_viewport
        same_layer = top[0].in_topmost_layer == second[0].in_topmost_layer
        if same_viewport and same_layer and abs(top[1] - second[1]) < 0.05:
            return None, 0.0

    return candidates[0]
