"""
Final test: Booking.com direct search URL with dates + nodriver
"""
import asyncio
import nodriver as uc
import json


async def test_booking_direct():
    print("=" * 60)
    print("Booking.com — direct search results URL with dates")
    print("=" * 60)

    browser = await uc.start(headless=True)
    url = (
        "https://www.booking.com/searchresults.en-gb.html"
        "?ss=Kathmandu"
        "&checkin=2026-06-05&checkout=2026-06-07"
        "&group_adults=2&no_rooms=1&group_children=0"
    )
    print(f"[1] Loading: {url[:80]}...")
    page = await browser.get(url)
    await asyncio.sleep(5)

    # Dismiss cookie + popups
    for text in ["Accept", "Dismiss"]:
        try:
            btn = await page.find(text, best_match=True, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

    # Dismiss sign-in popup
    try:
        dismiss = await page.query_selector("[aria-label='Dismiss sign-in info.']")
        if dismiss:
            await dismiss.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass

    # Wait + scroll
    await asyncio.sleep(3)
    for i in range(5):
        await page.evaluate(f"window.scrollTo(0, {(i+1) * 500})")
        await asyncio.sleep(1.5)
    await asyncio.sleep(2)

    title = await page.evaluate("document.title")
    current_url = await page.evaluate("window.location.href")
    print(f"[2] Title: {title}")
    print(f"    URL: {current_url[:100]}")

    # Try property cards
    cards = await page.query_selector_all("[data-testid='property-card']")
    print(f"[3] property-card count: {len(cards)}")

    if not cards:
        # Try to find ANY hotel-like content on page
        body_text = await page.evaluate("JSON.stringify(document.body.innerText.substring(0, 2000))")
        text = json.loads(body_text) if isinstance(body_text, str) else str(body_text)
        lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 5]
        print(f"\n[!] Page content ({len(lines)} lines):")
        for line in lines[:50]:
            print(f"  {line[:100]}")

        # Check for alternate hotel containers
        alt_counts = await page.evaluate("""JSON.stringify({
            hotelid: document.querySelectorAll('[data-hotelid]').length,
            srblock: document.querySelectorAll('.sr_property_block').length,
            card_container: document.querySelectorAll('[data-testid="property-card-container"]').length,
            title_link: document.querySelectorAll('[data-testid="title-link"]').length,
            any_card: document.querySelectorAll('[class*="card"]').length,
        })""")
        print(f"\n[!] Alt selectors: {alt_counts}")
    else:
        print("\n--- Booking.com Hotels ---")
        for i, card in enumerate(cards[:8]):
            try:
                info_raw = await card.evaluate("""(el) => JSON.stringify({
                    title: el.querySelector("[data-testid='title']")?.innerText || '?',
                    price: el.querySelector("[data-testid='price-and-discounted-price']")?.innerText || '',
                    score: el.querySelector("[data-testid='review-score']")?.innerText?.replace(/\\n/g, ' ')?.trim() || '',
                    addr: el.querySelector("[data-testid='address']")?.innerText || '',
                })""")
                info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
                print(f"  {i+1}. {info['title'].strip()}")
                if info.get('price'):
                    print(f"     Price: {info['price'].strip()[:60]}")
                if info.get('score'):
                    print(f"     Score: {info['score'][:50]}")
                if info.get('addr'):
                    print(f"     Addr:  {info['addr'][:60]}")
            except Exception as e:
                print(f"  {i+1}. (error: {e})")

    browser.stop()


if __name__ == "__main__":
    asyncio.run(test_booking_direct())
