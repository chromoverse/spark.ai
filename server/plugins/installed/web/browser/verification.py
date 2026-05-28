"""Composable goal verification predicates."""
import asyncio
from typing import Any, Optional


class GoalVerifier:
    """Composable predicates for goal verification."""
    
    async def url_contains(self, page: Any, frag: str) -> bool:
        """Check if URL contains fragment."""
        try:
            return frag.lower() in page.url.lower()
        except:
            return False
    
    async def element_exists(self, page: Any, target: str) -> bool:
        """Check if element exists."""
        try:
            from .perception.dom import find_element
            element, conf = await find_element(page, target)
            return element is not None and conf > 0.5
        except:
            return False
    
    async def text_appears(self, page: Any, text: str, *, timeout_s: float = 5.0) -> bool:
        """Check if text appears on page."""
        try:
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < timeout_s:
                content = await page.evaluate("() => document.body.innerText.toLowerCase()")
                if text.lower() in content:
                    return True
                await asyncio.sleep(0.5)
            return False
        except:
            return False
    
    async def video_playing(self, page: Any) -> bool:
        """Check if video is playing."""
        try:
            playing = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    return video && !video.paused && !video.ended;
                }
            """)
            return bool(playing)
        except:
            return False
    
    async def confirmation_number_found(self, page: Any) -> Optional[str]:
        """Extract confirmation number if present."""
        try:
            from .intelligence import extract_confirmation_number
            return await extract_confirmation_number(page)
        except:
            return None
    
    async def network_settled(self, page: Any, *, idle_s: float = 1.0) -> bool:
        """Check if network is idle (stub for Layer 4)."""
        await asyncio.sleep(idle_s)
        return True
    
    async def all_of(self, *predicates) -> bool:
        """All predicates must pass."""
        results = await asyncio.gather(*predicates, return_exceptions=True)
        return all(r is True for r in results)
    
    async def any_of(self, *predicates) -> bool:
        """Any predicate must pass."""
        results = await asyncio.gather(*predicates, return_exceptions=True)
        return any(r is True for r in results)
