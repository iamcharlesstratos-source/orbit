"""1688 / Alibaba supplier matcher.

Search 1688 by product name → return top listings with price (RMB → PHP), MOQ,
supplier ratings. Uses Playwright since 1688 is JS-heavy and blocks requests.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from playwright.sync_api import sync_playwright

log = logging.getLogger("pra.supplier")

# Approximate RMB → PHP exchange rate. Updated occasionally.
RMB_TO_PHP = 7.95

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _parse_price_yuan(text: str) -> float | None:
    """Extract first price in ¥/RMB from text."""
    if not text:
        return None
    m = re.search(r"[¥￥]?\s*([\d]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_moq(text: str) -> int | None:
    """Extract MOQ — '≥1', '10件起批', '50 pieces' etc."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*[件个]?\s*起", text) or re.search(r"≥\s*(\d+)", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def search_suppliers(keyword: str, max_results: int = 10,
                      headless: bool = True, timeout_ms: int = 30000) -> list[dict]:
    """Search 1688 for a keyword, return top supplier listings.

    Each result: {title, price_rmb, price_php, moq, supplier, url}
    """
    if not keyword.strip():
        return []
    search_url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote(keyword)}"
    log.info("1688 search: %r -> %s", keyword, search_url)

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=[
            "--disable-blink-features=AutomationControlled",
        ])
        ctx = browser.new_context(
            user_agent=_UA,
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(page)
        except Exception:
            pass

        try:
            page.goto(search_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)

            # 1688 uses dynamic class names. Anchor on common card patterns:
            # offers usually contain "¥" price text.
            try:
                page.wait_for_selector("text=/[¥￥]\\s*\\d/", timeout=10000)
            except Exception:
                log.warning("1688 didn't render results in time (likely blocked or login required)")

            # Scroll once to trigger lazy load
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(1500)

            # Find cards anchored on price element, walk up
            price_locs = page.locator("text=/[¥￥]\\s*\\d/")
            count = min(price_locs.count(), max_results * 3)

            seen_urls: set[str] = set()
            for i in range(count):
                if len(results) >= max_results:
                    break
                try:
                    anchor = price_locs.nth(i)
                    # Walk up to a card container with enough text
                    card = None
                    card_text = ""
                    for level in (4, 5, 6, 7, 8):
                        try:
                            c = anchor.locator(f"xpath=ancestor::div[{level}]")
                            t = c.inner_text(timeout=600)
                            if "¥" in t or "￥" in t:
                                card = c
                                card_text = t
                                if len(t) > 30:
                                    break
                        except Exception:
                            continue
                    if not card or not card_text:
                        continue

                    # Extract title (longest non-numeric line)
                    title = ""
                    for line in card_text.splitlines():
                        s = line.strip()
                        if not s or "¥" in s or "￥" in s:
                            continue
                        if len(s) > len(title) and not s.isdigit():
                            title = s
                    if not title:
                        continue

                    price_rmb = _parse_price_yuan(card_text)
                    moq = _parse_moq(card_text)

                    # Get product URL
                    url = ""
                    supplier = ""
                    try:
                        link = card.locator("a[href*='1688.com']").first
                        url = link.get_attribute("href") or ""
                    except Exception:
                        pass
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # Supplier name often appears in a separate anchor
                    try:
                        sup = card.locator("a[href*='shop']").first
                        supplier = (sup.inner_text(timeout=400) or "").strip()[:60]
                    except Exception:
                        pass

                    results.append({
                        "title": title[:140],
                        "price_rmb": price_rmb,
                        "price_php": round(price_rmb * RMB_TO_PHP, 2) if price_rmb else None,
                        "moq": moq,
                        "supplier": supplier,
                        "url": url[:500],
                    })
                except Exception as e:
                    log.debug("card parse error: %s", e)
                    continue
        finally:
            ctx.close()
            browser.close()

    log.info("1688: %d suppliers parsed for %r", len(results), keyword)
    return results
