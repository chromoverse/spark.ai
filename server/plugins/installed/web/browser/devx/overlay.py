"""Visual debugging overlay - highlights elements with confidence colors."""
import os
from typing import Any, Optional

# Overlay enabled by env var or dry-run mode
OVERLAY_ENABLED = os.getenv("BROWSER_DEBUG_OVERLAY", "0") == "1"

# Injected JS for drawing boxes
OVERLAY_SCRIPT = """
(() => {
  if (window.__sparkOverlay) return;
  
  window.__sparkOverlay = {
    boxes: [],
    
    clear() {
      this.boxes.forEach(box => box.remove());
      this.boxes = [];
    },
    
    highlight(selector, label, confidence) {
      const el = document.querySelector(selector);
      if (!el) return;
      
      const rect = el.getBoundingClientRect();
      const box = document.createElement('div');
      
      // Color based on confidence
      let color = '#00ff00'; // green (high)
      if (confidence < 0.7) color = '#ff0000'; // red (low)
      else if (confidence < 0.9) color = '#ffff00'; // yellow (medium)
      
      box.style.cssText = `
        position: fixed;
        left: ${rect.left}px;
        top: ${rect.top}px;
        width: ${rect.width}px;
        height: ${rect.height}px;
        border: 3px solid ${color};
        background: ${color}22;
        pointer-events: none;
        z-index: 999999;
        box-sizing: border-box;
      `;
      
      // Label
      const labelEl = document.createElement('div');
      labelEl.textContent = `${label} (${(confidence * 100).toFixed(0)}%)`;
      labelEl.style.cssText = `
        position: absolute;
        top: -25px;
        left: 0;
        background: ${color};
        color: #000;
        padding: 2px 6px;
        font-size: 12px;
        font-family: monospace;
        white-space: nowrap;
      `;
      box.appendChild(labelEl);
      
      document.body.appendChild(box);
      this.boxes.push(box);
      
      // Auto-remove after 3s
      setTimeout(() => {
        box.remove();
        this.boxes = this.boxes.filter(b => b !== box);
      }, 3000);
    }
  };
})();
"""


async def inject_overlay(page: Any):
    """Inject overlay script into page."""
    if not OVERLAY_ENABLED:
        return
    try:
        await page.evaluate(OVERLAY_SCRIPT)
    except:
        pass


async def highlight_element(
    page: Any,
    selector: str,
    label: str,
    confidence: float,
    *,
    enabled: Optional[bool] = None
):
    """Highlight element with colored box."""
    if enabled is None:
        enabled = OVERLAY_ENABLED
    
    if not enabled:
        return
    
    try:
        await inject_overlay(page)
        await page.evaluate(
            f"window.__sparkOverlay.highlight({repr(selector)}, {repr(label)}, {confidence})"
        )
    except:
        pass


async def clear_overlay(page: Any):
    """Clear all overlay boxes."""
    try:
        await page.evaluate("window.__sparkOverlay?.clear()")
    except:
        pass
