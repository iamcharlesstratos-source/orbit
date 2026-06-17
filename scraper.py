"""Meta Ads Library scraper for Product Research Agent."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PWTimeout


log = logging.getLogger("pra.scraper")

META_LIBRARY_BASE = "https://www.facebook.com/ads/library/"

_INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿\xa0]")


def _clean(s: str) -> str:
    return _INVISIBLE_RE.sub("", s).strip()


def resolve_landing_url(url: str) -> str:
    """Unwrap Facebook's l.facebook.com redirector so Excel cells link directly to Shopee/Lazada/etc."""
    if not url or "l.facebook.com" not in url:
        return url
    try:
        u = parse_qs(urlparse(url).query).get("u", [""])[0]
        if u:
            return unquote(u)[:500]
    except Exception:
        pass
    return url


@dataclass
class Ad:
    keyword: str
    niche: str
    library_id: str = ""
    page_name: str = ""
    start_date: str = ""
    end_date: str = ""
    is_active: bool = False
    days_running: int = 0
    platforms: str = ""
    ad_text: str = ""
    landing_url: str = ""
    media_type: str = ""
    media_url: str = ""
    scraped_at: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def build_search_url(keyword: str, country: str, active_status: str) -> str:
    params = {
        "active_status": active_status,
        "ad_type": "all",
        "country": country,
        "q": keyword,
        "search_type": "keyword_unordered",
        "media_type": "all",
    }
    return META_LIBRARY_BASE + "?" + urlencode(params)


def dismiss_overlays(page: Page) -> None:
    """Close cookie banner and login popup if shown."""
    for label in ("Decline optional cookies", "Allow all cookies", "Only allow essential cookies"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                break
        except Exception:
            pass
    try:
        close = page.get_by_role("button", name="Close")
        if close.count() > 0:
            close.first.click(timeout=1500)
            page.wait_for_timeout(500)
    except Exception:
        pass


def normalize_date(raw: str) -> str:
    if not raw:
        return ""
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def days_between(start_iso: str, end_iso: str) -> int:
    if not start_iso:
        return 0
    try:
        start = date.fromisoformat(start_iso)
    except ValueError:
        return 0
    if end_iso:
        try:
            end = date.fromisoformat(end_iso)
        except ValueError:
            end = date.today()
    else:
        end = date.today()
    return max(0, (end - start).days)


def parse_card_text(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    m = re.search(r"Library ID:\s*([0-9]+)", text)
    if m:
        out["library_id"] = m.group(1)

    header = text.split("Library ID")[0]
    out["is_active"] = bool(re.search(r"\bActive\b", header))

    m = re.search(
        r"Started running on ([A-Z][a-z]{2,8} \d{1,2}, \d{4})"
        r"(?:\s*[-–]\s*([A-Z][a-z]{2,8} \d{1,2}, \d{4}))?",
        text,
    )
    if m:
        out["start_date_raw"] = m.group(1)
        out["end_date_raw"] = m.group(2) or ""

    return out


def detect_platforms(card) -> str:
    """Detect which Meta platforms an ad runs on. Returns comma-separated list.

    Phase 17.7 — Meta encodes platform icons as CSS backgrounds, BUT they also
    sometimes appear as aria-label-bearing img elements OR with text labels
    in deep-detail cards. Try multiple heuristics; return what we can find.
    """
    found: set[str] = set()
    try:
        text = card.inner_text(timeout=800) if hasattr(card, "inner_text") else ""
    except Exception:
        text = ""
    text_low = text.lower()
    # Explicit text mentions in card (rare in list view, common in detail view)
    if "instagram" in text_low:
        found.add("Instagram")
    if "facebook" in text_low and "facebook.com" not in text_low:
        # avoid matching the literal URL host
        found.add("Facebook")
    if "audience network" in text_low or "audience network" in text_low:
        found.add("Audience Network")
    if "messenger" in text_low:
        found.add("Messenger")
    # aria-label image alts (some cards have these)
    try:
        for el in card.locator("[aria-label*='Instagram'], [aria-label*='Facebook'], "
                               "[aria-label*='Audience Network'], [aria-label*='Messenger']").all()[:6]:
            label = el.get_attribute("aria-label") or ""
            if "Instagram" in label:
                found.add("Instagram")
            elif "Facebook" in label:
                found.add("Facebook")
            elif "Audience Network" in label:
                found.add("Audience Network")
            elif "Messenger" in label:
                found.add("Messenger")
    except Exception:
        pass
    return ",".join(sorted(found))


_UI_LABELS = {
    "Active", "Inactive", "Sponsored", "Open Dropdown", "Open menu", "Options",
    "See ad details", "See summary details", "Save", "Report ad", "Like", "Comment",
    "Share", "More", "Photo", "Video", "Carousel",
}


def extract_page_name(card) -> str:
    """Page name = anchor text on a link to a real FB page (not /ads/library)."""
    try:
        links = card.locator("a[href*='facebook.com']").all()
        for a in links[:8]:
            href = a.get_attribute("href") or ""
            if "/ads/library" in href or "/help/" in href:
                continue
            text = _clean(a.inner_text(timeout=500) or "")
            if text and len(text) >= 2 and text not in _UI_LABELS and not text.startswith("http"):
                return text[:120]
    except Exception:
        pass
    return ""


def _card_ancestor(page: Page, anchor):
    """Walk up from the 'Library ID' text node to a card-sized container."""
    for levels in (8, 9, 10, 11, 12, 7, 6):
        try:
            card = anchor.locator(f"xpath=ancestor::div[{levels}]")
            text = card.inner_text(timeout=800)
            if "Started running on" in text:
                return card, text
        except Exception:
            continue
    return None, ""


def extract_ads_from_page(page: Page, keyword: str, niche: str) -> list[Ad]:
    ads: list[Ad] = []
    anchors = page.locator("text=/Library ID:\\s*\\d+/")
    count = anchors.count()
    seen: set[str] = set()

    for i in range(count):
        try:
            anchor = anchors.nth(i)
            card, text = _card_ancestor(page, anchor)
            if not card or not text:
                continue

            parsed = parse_card_text(text)
            lib_id = parsed.get("library_id", "")
            if not lib_id or lib_id in seen:
                continue
            seen.add(lib_id)

            page_name = extract_page_name(card)
            if not page_name:
                for line in text.splitlines():
                    s = _clean(line)
                    if not s or s in _UI_LABELS:
                        continue
                    if any(s.startswith(p) for p in (
                        "Library ID", "Started running", "Platforms",
                        "See ad details", "See summary",
                    )):
                        continue
                    if re.match(r"^[A-Z][a-z]{2,8} \d{1,2}, \d{4}", s):
                        continue
                    page_name = s[:120]
                    break

            body_lines: list[str] = []
            after_page = False
            for line in text.splitlines():
                s = _clean(line)
                if not s:
                    continue
                if not after_page:
                    if s == page_name:
                        after_page = True
                    continue
                if any(s.startswith(p) for p in (
                    "Library ID", "Started running", "Platforms", "Active", "Inactive",
                    "Sponsored", "See ad details", "See summary",
                )):
                    continue
                body_lines.append(s)
            ad_text = " ".join(body_lines)[:600]

            landing_url = ""
            try:
                links = card.locator("a[href^='https://']").all()
                fallback_fb = ""
                for a in links[:15]:
                    href = a.get_attribute("href") or ""
                    if not href or "facebook.com/ads/library" in href:
                        continue
                    resolved = resolve_landing_url(href)
                    # Prefer external marketplace links (Shopee/Lazada/TikTok/etc) over FB page links
                    if "facebook.com" not in resolved and "messenger.com" not in resolved:
                        landing_url = resolved[:500]
                        break
                    if not fallback_fb:
                        fallback_fb = resolved[:500]
                if not landing_url:
                    landing_url = fallback_fb
            except Exception:
                pass

            start_iso = normalize_date(parsed.get("start_date_raw", ""))
            end_iso = normalize_date(parsed.get("end_date_raw", ""))

            try:
                from creatives import detect_media
                media_type, media_url = detect_media(card)
            except Exception:
                media_type, media_url = "", ""

            ads.append(Ad(
                keyword=keyword,
                niche=niche,
                library_id=lib_id,
                page_name=page_name,
                start_date=start_iso,
                end_date=end_iso,
                is_active=parsed.get("is_active", False),
                days_running=days_between(start_iso, end_iso),
                platforms=detect_platforms(card),
                ad_text=ad_text,
                landing_url=landing_url,
                media_type=media_type,
                media_url=media_url,
                scraped_at=datetime.now().isoformat(timespec="seconds"),
            ))
        except Exception:
            continue
    return ads


def scrape_keyword(
    page: Page,
    keyword: str,
    niche: str,
    country: str,
    active_status: str,
    max_ads: int,
    max_scrolls: int,
    pause_ms: int,
) -> list[Ad]:
    url = build_search_url(keyword, country, active_status)
    log.info("  -> %r: navigating", keyword)
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    dismiss_overlays(page)

    try:
        page.wait_for_selector("text=/Library ID:/", timeout=15000)
    except PWTimeout:
        log.warning("     no ads found for %r", keyword)
        return []

    seen_count = 0
    stagnant = 0
    for _ in range(max_scrolls):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(pause_ms)
        current = page.locator("text=/Library ID:/").count()
        if current >= max_ads:
            break
        if current == seen_count:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
            seen_count = current

    ads = extract_ads_from_page(page, keyword, niche)
    log.info("     parsed %d unique ads", len(ads))
    return ads[:max_ads]


def run(config: dict, niches: list[str]) -> dict[str, list[Ad]]:
    results: dict[str, list[Ad]] = {n: [] for n in niches}
    seen_global: set[str] = set()  # global dedup across keywords
    empty_keywords = 0
    total_keywords = 0

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(
            headless=config.get("headless", True),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        # Apply stealth (mask Playwright/Chromium fingerprints from Meta's bot detection)
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(page)
            log.info("Stealth mode applied to scraper context")
        except ImportError:
            log.debug("playwright-stealth not installed — install via `pip install playwright-stealth`")
        except Exception as e:
            log.debug("Stealth setup failed (non-fatal): %s", e)

        # Phase 11.5: retry with exponential backoff on Playwright failures
        # (timeouts, navigation errors, captcha challenges). Up to 3 attempts per keyword.
        _RETRY_DELAYS_MS = [5000, 15000, 45000]  # 5s, 15s, 45s

        for niche in niches:
            keywords = config["niches"].get(niche, [])
            log.info("[%s] %d keywords", niche, len(keywords))
            for kw in keywords:
                total_keywords += 1
                ads: list = []
                last_err: Exception | None = None
                for attempt_idx in range(len(_RETRY_DELAYS_MS) + 1):
                    try:
                        ads = scrape_keyword(
                            page=page,
                            keyword=kw,
                            niche=niche,
                            country=config["country"],
                            active_status=config["active_status"],
                            max_ads=config["max_ads_per_keyword"],
                            max_scrolls=config["max_scroll_rounds"],
                            pause_ms=config["scroll_pause_ms"],
                        )
                        last_err = None
                        break  # success
                    except Exception as e:
                        last_err = e
                        if attempt_idx < len(_RETRY_DELAYS_MS):
                            delay = _RETRY_DELAYS_MS[attempt_idx]
                            log.warning(
                                "     attempt %d/%d failed for %r: %s — retrying in %dms",
                                attempt_idx + 1, len(_RETRY_DELAYS_MS) + 1, kw,
                                str(e)[:120], delay,
                            )
                            try:
                                page.wait_for_timeout(delay)
                            except Exception:
                                pass
                        else:
                            log.error(
                                "     gave up on %r after %d attempts — last error: %s",
                                kw, len(_RETRY_DELAYS_MS) + 1, str(e)[:200],
                            )
                if last_err is not None and not ads:
                    # all retries failed for this keyword — track but continue
                    empty_keywords += 1
                    continue
                if not ads:
                    empty_keywords += 1
                fresh = [a for a in ads if a.library_id not in seen_global]
                for a in fresh:
                    seen_global.add(a.library_id)
                results[niche].extend(fresh)
                if len(fresh) < len(ads):
                    log.info("     dedup: %d duplicates filtered", len(ads) - len(fresh))
                page.wait_for_timeout(1500)

        context.close()
        browser.close()

    if total_keywords >= 2 and empty_keywords >= max(2, total_keywords // 3):
        log.warning(
            "HEALTH CHECK: %d/%d keywords returned 0 ads — Meta selectors may be stale or you're being throttled.",
            empty_keywords, total_keywords,
        )

    return results
