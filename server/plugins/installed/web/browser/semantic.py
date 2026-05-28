"""Semantic action verbs with confidence scoring."""
import asyncio
from dataclasses import dataclass
from typing import Optional, Any
from .errors import BrowserErrorType
from .perception.dom import wait_dom_stable, find_element
from .perception.vision import take_screenshot
from .policies import CONFIDENCE_GATE


@dataclass
class ActionResult:
    ok: bool
    action: str
    target: Optional[str]
    confidence: float
    error_type: Optional[BrowserErrorType] = None
    error_detail: Optional[str] = None
    screenshot_before: Optional[str] = None
    screenshot_after: Optional[str] = None
    evidence: Optional[dict] = None


async def goto(page: Any, url: str, runtime: Any) -> ActionResult:
    """Navigate to URL."""
    try:
        screenshot_before = await take_screenshot(page)
        
        if runtime.dry_run:
            return ActionResult(
                ok=True,
                action="goto",
                target=url,
                confidence=1.0,
                evidence={"dry_run": True, "url": url}
            )
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        stable = await wait_dom_stable(page)
        
        screenshot_after = await take_screenshot(page)
        
        if not response or response.status >= 400:
            return ActionResult(
                ok=False,
                action="goto",
                target=url,
                confidence=0.0,
                error_type=BrowserErrorType.NAVIGATION_FAILED,
                error_detail=f"HTTP {response.status if response else 'unknown'}",
                screenshot_before=screenshot_before.hex() if screenshot_before else None,
                screenshot_after=screenshot_after.hex() if screenshot_after else None
            )
        
        conf = 0.9 if stable else 0.7
        return ActionResult(
            ok=True,
            action="goto",
            target=url,
            confidence=conf,
            screenshot_before=screenshot_before.hex() if screenshot_before else None,
            screenshot_after=screenshot_after.hex() if screenshot_after else None,
            evidence={"status": response.status, "stable": stable}
        )
    except Exception as e:
        return ActionResult(
            ok=False,
            action="goto",
            target=url,
            confidence=0.0,
            error_type=BrowserErrorType.TIMEOUT,
            error_detail=str(e)
        )


async def click_by_text(page: Any, text: str, runtime: Any, *, kind: Optional[str] = None) -> ActionResult:
    """Click element by text."""
    try:
        screenshot_before = await take_screenshot(page)
        
        stable = await wait_dom_stable(page)
        if not stable:
            return ActionResult(
                ok=False,
                action="click",
                target=text,
                confidence=0.0,
                error_type=BrowserErrorType.DOM_NOT_STABLE,
                error_detail="DOM did not stabilize"
            )
        
        element, strategy_conf = await find_element(page, text, kind=kind)
        if not element:
            return ActionResult(
                ok=False,
                action="click",
                target=text,
                confidence=0.0,
                error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
                error_detail=f"No element found for '{text}'"
            )
        
        if runtime.dry_run:
            # In dry-run, highlight the element
            from .devx.overlay import highlight_element
            await highlight_element(
                page,
                element.selector or f"text={text}",
                f"click: {text}",
                strategy_conf,
                enabled=True
            )
            return ActionResult(
                ok=True,
                action="click",
                target=text,
                confidence=strategy_conf,
                evidence={"dry_run": True, "selector": element.selector, "strategy_conf": strategy_conf}
            )
        
        # Perform click
        old_url = page.url  # Capture URL before click
        if element.selector:
            await page.click(element.selector)
        else:
            # Fallback to text-based click
            await page.click(f"text={text}")
        
        await asyncio.sleep(0.5)  # Brief wait for action to take effect
        screenshot_after = await take_screenshot(page)
        
        # Post-check: verify action had effect (simple heuristic)
        post_check_multiplier = 1.0
        try:
            new_url = page.url
            if new_url != old_url:  # URL changed
                post_check_multiplier = 1.05
        except:
            pass
        
        final_conf = min(strategy_conf * post_check_multiplier, 1.0)
        
        if final_conf < CONFIDENCE_GATE:
            return ActionResult(
                ok=False,
                action="click",
                target=text,
                confidence=final_conf,
                error_type=BrowserErrorType.LOW_CONFIDENCE,
                error_detail=f"Confidence {final_conf:.2f} below gate {CONFIDENCE_GATE}",
                screenshot_before=screenshot_before.hex() if screenshot_before else None,
                screenshot_after=screenshot_after.hex() if screenshot_after else None,
                evidence={"selector": element.selector, "strategy_conf": strategy_conf}
            )
        
        return ActionResult(
            ok=True,
            action="click",
            target=text,
            confidence=final_conf,
            screenshot_before=screenshot_before.hex() if screenshot_before else None,
            screenshot_after=screenshot_after.hex() if screenshot_after else None,
            evidence={"selector": element.selector, "strategy_conf": strategy_conf}
        )
    except Exception as e:
        return ActionResult(
            ok=False,
            action="click",
            target=text,
            confidence=0.0,
            error_type=BrowserErrorType.TIMEOUT,
            error_detail=str(e)
        )


async def fill_form(page: Any, fields: dict[str, str], runtime: Any) -> ActionResult:
    """Fill form fields."""
    try:
        screenshot_before = await take_screenshot(page)
        
        stable = await wait_dom_stable(page)
        if not stable:
            return ActionResult(
                ok=False,
                action="fill_form",
                target=str(fields),
                confidence=0.0,
                error_type=BrowserErrorType.DOM_NOT_STABLE,
                error_detail="DOM did not stabilize"
            )
        
        if runtime.dry_run:
            return ActionResult(
                ok=True,
                action="fill_form",
                target=str(fields),
                confidence=0.95,
                evidence={"dry_run": True, "fields": fields}
            )
        
        filled = []
        for label, value in fields.items():
            element, conf = await find_element(page, label, kind="input")
            if not element:
                continue

            # Prefer the captured selector. When the input has no id /
            # testid (very common on framework-rendered pages), fall
            # back to an attribute-based Playwright locator built from
            # whatever signal we did capture. Silently skipping here is
            # how the YouTube search box was getting missed.
            try:
                if element.selector:
                    await page.fill(element.selector, value)
                elif element.aria_label:
                    await page.fill(
                        f'input[aria-label="{element.aria_label}"]', value
                    )
                elif element.placeholder:
                    await page.fill(
                        f'input[placeholder="{element.placeholder}"]', value
                    )
                else:
                    continue
                filled.append(label)
            except Exception:
                # Locator may not be unique; try the most-visible match.
                try:
                    if element.aria_label:
                        loc = page.locator(
                            f'input[aria-label="{element.aria_label}"]:visible'
                        ).first
                        await loc.fill(value)
                        filled.append(label)
                except Exception:
                    pass
        
        screenshot_after = await take_screenshot(page)
        
        success_rate = len(filled) / len(fields) if fields else 0
        final_conf = success_rate * 0.95
        
        if final_conf < CONFIDENCE_GATE:
            return ActionResult(
                ok=False,
                action="fill_form",
                target=str(fields),
                confidence=final_conf,
                error_type=BrowserErrorType.LOW_CONFIDENCE,
                error_detail=f"Only filled {len(filled)}/{len(fields)} fields",
                screenshot_before=screenshot_before.hex() if screenshot_before else None,
                screenshot_after=screenshot_after.hex() if screenshot_after else None,
                evidence={"filled": filled, "requested": list(fields.keys())}
            )
        
        return ActionResult(
            ok=True,
            action="fill_form",
            target=str(fields),
            confidence=final_conf,
            screenshot_before=screenshot_before.hex() if screenshot_before else None,
            screenshot_after=screenshot_after.hex() if screenshot_after else None,
            evidence={"filled": filled}
        )
    except Exception as e:
        return ActionResult(
            ok=False,
            action="fill_form",
            target=str(fields),
            confidence=0.0,
            error_type=BrowserErrorType.TIMEOUT,
            error_detail=str(e)
        )


async def wait_navigation(page: Any, *, timeout_s: float = 15.0) -> ActionResult:
    """Wait for navigation to complete."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_s * 1000)
        stable = await wait_dom_stable(page)
        conf = 0.95 if stable else 0.75
        return ActionResult(
            ok=True,
            action="wait_navigation",
            target=page.url,
            confidence=conf,
            evidence={"stable": stable}
        )
    except Exception as e:
        return ActionResult(
            ok=False,
            action="wait_navigation",
            target=None,
            confidence=0.0,
            error_type=BrowserErrorType.TIMEOUT,
            error_detail=str(e)
        )
