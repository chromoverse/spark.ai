"""Vision layer - screenshot and analysis."""
from typing import Any

VISION_AVAILABLE = False


async def take_screenshot(page: Any) -> bytes:
    """Take screenshot of current viewport."""
    return await page.screenshot(full_page=False)


async def analyze_screenshot(image: bytes, question: str) -> dict:
    """Analyze screenshot (stub - real vision model swap-in later)."""
    return {
        "available": False,
        "fallback": "dom",
        "message": "Vision analysis not yet implemented"
    }
