"""Reusable action step library."""
from ..action_graph import ActionStep, StepContext
from ..semantic import goto, click_by_text, fill_form, wait_navigation
from ..state_machine import FlowState


def go_to_home(base_url: str) -> ActionStep:
    """Navigate to home page."""
    async def run(ctx: StepContext):
        return await goto(ctx.page, base_url, ctx.runtime)
    
    return ActionStep(
        name="go_to_home",
        goal=f"Navigate to {base_url}",
        run=run
    )


def fill_search_box(field_label: str = "Search") -> ActionStep:
    """Fill search input."""
    async def run(ctx: StepContext):
        return await fill_form(ctx.page, {field_label: ctx.intent}, ctx.runtime)
    
    return ActionStep(
        name="fill_search_box",
        goal=f"Fill {field_label} with query",
        run=run
    )


def submit_search(button_text: str = "Search") -> ActionStep:
    """Submit a search form.

    Tries the labeled button first. If no such button exists (very common —
    YouTube's submit is an unlabeled magnifier icon), falls back to
    pressing Enter, which submits any HTML form with a focused text input.
    """
    from ..semantic import ActionResult
    from ..errors import BrowserErrorType

    async def run(ctx: StepContext):
        # Attempt 1: click an actual button.
        result = await click_by_text(ctx.page, button_text, ctx.runtime, kind="button")
        if result.ok:
            await wait_navigation(ctx.page)
            return result

        # Attempt 2: press Enter. fill_search_box just focused an input
        # in the previous step, so the active element is the search field.
        try:
            await ctx.page.keyboard.press("Enter")
            await wait_navigation(ctx.page)
            return ActionResult(
                ok=True, action="submit_search", target="<enter>",
                confidence=0.85, evidence={"strategy": "keyboard_enter"},
            )
        except Exception as e:
            return ActionResult(
                ok=False, action="submit_search", target=button_text,
                confidence=0.0,
                error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
                error_detail=f"no {button_text!r} button and Enter failed: {e}",
            )

    return ActionStep(
        name="submit_search",
        goal=f"Submit search (click {button_text!r} or press Enter)",
        run=run,
    )


def wait_for_results() -> ActionStep:
    """Wait for search results to load."""
    async def run(ctx: StepContext):
        return await wait_navigation(ctx.page)
    
    return ActionStep(
        name="wait_for_results",
        goal="Wait for results to load",
        run=run
    )


def click_first_result(link_pattern: str = "") -> ActionStep:
    """Click first search result whose href contains ``link_pattern``.

    Uses Playwright's locator API directly (not extract_ui_tree) so we
    can match anchors by `href*=...` — the previous implementation could
    only match by selector/text, neither of which carries the href, so
    it always fell through to clicking the first link on the page
    (e.g. the site logo). It also wouldn't wait for a real result to
    actually render.
    """
    async def run(ctx: StepContext):
        from ..semantic import ActionResult
        from ..errors import BrowserErrorType

        page = ctx.page
        try:
            if link_pattern:
                locator = page.locator(f'a[href*="{link_pattern}"]:visible').first
            else:
                locator = page.locator('a:visible').first

            # Wait for at least one such link to appear (search results
            # often render after the SPA framework hydrates).
            try:
                await locator.wait_for(state="visible", timeout=10_000)
            except Exception:
                return ActionResult(
                    ok=False, action="click_first_result",
                    target=link_pattern or "first link", confidence=0.0,
                    error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
                    error_detail=f"No visible link matching {link_pattern!r}",
                )

            href = await locator.get_attribute("href")
            await locator.scroll_into_view_if_needed(timeout=3_000)
            await locator.click(timeout=5_000)
            await wait_navigation(page)

            return ActionResult(
                ok=True, action="click_first_result",
                target=href or link_pattern, confidence=0.9,
                evidence={"link_pattern": link_pattern, "href": href},
            )
        except Exception as e:
            return ActionResult(
                ok=False, action="click_first_result",
                target=link_pattern, confidence=0.0,
                error_type=BrowserErrorType.TIMEOUT,
                error_detail=str(e),
            )

    return ActionStep(
        name="click_first_result",
        goal=f"Click first result{' matching ' + link_pattern if link_pattern else ''}",
        run=run,
    )


def open_detail_page() -> ActionStep:
    """Open detail page (generic)."""
    return click_first_result()


def add_to_cart(button_text: str = "Add to cart") -> ActionStep:
    """Click add to cart button."""
    async def run(ctx: StepContext):
        return await click_by_text(ctx.page, button_text, ctx.runtime, kind="button")
    
    return ActionStep(
        name="add_to_cart",
        goal=f"Click {button_text}",
        run=run
    )


def go_to_cart() -> ActionStep:
    """Navigate to cart."""
    async def run(ctx: StepContext):
        return await click_by_text(ctx.page, "Cart", ctx.runtime)
    
    return ActionStep(
        name="go_to_cart",
        goal="Navigate to cart",
        run=run
    )


def fill_address_form() -> ActionStep:
    """Fill address form (stub)."""
    async def run(ctx: StepContext):
        # Would use Chrome autofill in real implementation
        return None
    
    return ActionStep(
        name="fill_address_form",
        goal="Fill address form",
        run=run
    )


def verify_url_contains(fragment: str) -> ActionStep:
    """Verify URL contains fragment."""
    async def run(ctx: StepContext):
        from ..verification import GoalVerifier
        verifier = GoalVerifier()
        verified = await verifier.url_contains(ctx.page, fragment)
        return type('Result', (), {'ok': verified, 'confidence': 1.0 if verified else 0.0})()
    
    return ActionStep(
        name="verify_url_contains",
        goal=f"Verify URL contains '{fragment}'",
        run=run
    )


def verify_text_appears(text: str) -> ActionStep:
    """Verify text appears on page."""
    async def run(ctx: StepContext):
        from ..verification import GoalVerifier
        verifier = GoalVerifier()
        verified = await verifier.text_appears(ctx.page, text)
        return type('Result', (), {'ok': verified, 'confidence': 1.0 if verified else 0.0})()
    
    return ActionStep(
        name="verify_text_appears",
        goal=f"Verify text '{text}' appears",
        run=run
    )
