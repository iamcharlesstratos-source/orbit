"""TikTok Creative Center 'Top Ads' scraper for PH.

Source: https://ads.tiktok.com/business/creativecenter/topads/
Captures top-performing ads from PH advertisers as ranked by TikTok itself.

Reality check: TikTok's anti-bot is stricter than Meta's. This scraper:
  - Works for the public 'Top Ads' inspiration page (no login required)
  - Captures: advertiser, likes, plays, ctr, duration, industry, thumbnail
  - May break when TikTok ships UI changes — selectors are best-effort
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

log = logging.getLogger("pra.tiktok")

TOP_ADS_BASE = "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pad/en"

# TikTok Creative Center groups ads by industry, not free-text keyword.
# Map our PH ecommerce niches to TikTok's industry filter.
INDUSTRY_MAP = {
    "capsule": "21000000000",       # Health & Wellness
    "cream": "20000000000",         # Beauty & Personal Care
    "oil": "20000000000",           # Beauty & Personal Care
    "coffee": "23000000000",        # Food & Beverage
    # leave empty to scrape all industries:
    "all": "",
}


def build_url(country: str = "PH", period: int = 7, industry: str = "") -> str:
    params = {
        "countryCode": country,
        "period": period,
        "sort_by": "for_you",
    }
    if industry:
        params["industry"] = industry
    return TOP_ADS_BASE + "?" + urlencode(params)


def _parse_engagement_number(text: str) -> int:
    """'1.2K' -> 1200, '3.4M' -> 3400000, '987' -> 987."""
    text = (text or "").strip().replace(",", "")
    m = re.search(r"([\d.]+)\s*([KMB]?)", text, re.IGNORECASE)
    if not m:
        return 0
    try:
        val = float(m.group(1))
    except ValueError:
        return 0
    suffix = m.group(2).upper()
    if suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    elif suffix == "B":
        val *= 1_000_000_000
    return int(val)


def _dismiss_consent(page: Page) -> None:
    for label in ("Accept all", "Accept All", "Accept", "I agree", "Agree", "Got it"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(400)
                break
        except Exception:
            continue


def _scrape_top_ads_page(page: Page, max_ads: int, scroll_rounds: int) -> list[dict]:
    """Find ad cards on the Top Ads page. Cards are typically wrapped in
    items with engagement icons (like, play) — anchor on those."""
    # Wait for any card to appear
    try:
        page.wait_for_selector("xpath=//*[contains(text(),'Like') or contains(text(),'Play')]", timeout=15000)
    except PWTimeout:
        log.warning("TikTok: top-ads cards didn't render in time.")
        return []

    seen_count = 0
    stagnant = 0
    for _ in range(scroll_rounds):
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(1800)
        try:
            current = page.locator("xpath=//*[@aria-label='Like' or @aria-label='Play count']").count()
        except Exception:
            current = 0
        if current >= max_ads:
            break
        if current == seen_count:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
            seen_count = current

    # Approach: each ad card contains "Like", "Play", and a brand name.
    # Find each card by anchoring on like/play icons and walking up to a stable parent.
    ads: list[dict] = []
    seen_ids: set[str] = set()
    try:
        anchors = page.locator(
            "xpath=//*[contains(@class,'Card') or contains(@class,'card')][.//*[contains(text(),'Like') or contains(text(),'Play')]]"
        )
        count = anchors.count()
    except Exception:
        count = 0

    if count == 0:
        # Fallback heuristic: look for items containing both video thumbnail and a numeric engagement
        anchors = page.locator("xpath=//div[descendant::img and descendant::*[contains(text(),'Like') or contains(text(),'Play')]]")
        count = min(anchors.count(), 200)

    for i in range(count):
        try:
            card = anchors.nth(i)
            text = card.inner_text(timeout=1500)
            if not text or len(text) < 10:
                continue

            # Use the card's HTML signature as a synthetic ad_id when no explicit ID
            try:
                href_el = card.locator("a[href*='/detail/'], a[href*='topads']").first
                detail_url = href_el.get_attribute("href") or ""
            except Exception:
                detail_url = ""

            # Synth ID: detail URL slug, else first 60 chars of text hash
            if detail_url:
                m = re.search(r"/(?:topads|detail)/([A-Za-z0-9_-]+)", detail_url)
                ad_id = m.group(1) if m else detail_url[-40:]
            else:
                ad_id = f"sig:{abs(hash(text[:200])) % 10**12}"

            if ad_id in seen_ids:
                continue
            seen_ids.add(ad_id)

            # Parse engagement from text — labels like "Like\n1.2K" or "Play\n3.4M"
            likes = 0
            plays = 0
            for m in re.finditer(r"(Like|Play|Share|Comment)\D*([\d.,]+\s*[KkMmBb]?)", text):
                label = m.group(1).lower()
                num = _parse_engagement_number(m.group(2))
                if label == "like":
                    likes = max(likes, num)
                elif label == "play":
                    plays = max(plays, num)

            # CTR pattern: "CTR\n4.2%"
            ctr = 0.0
            m = re.search(r"CTR[^\d]*([\d.]+)\s*%?", text)
            if m:
                try:
                    ctr = float(m.group(1))
                except ValueError:
                    pass

            # Duration pattern: "0:25" or "00:25"
            duration_s = 0
            m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
            if m:
                duration_s = int(m.group(1)) * 60 + int(m.group(2))

            # Advertiser parsing — TikTok Creative Center shows filter labels (Beauty, Fashion,
            # etc.) near cards. We must NOT pick those. Strategy:
            #   1. Prefer @-prefixed handles (real usernames)
            #   2. Otherwise, skip known filter/industry/UI labels
            #   3. Skip duration labels (0:15) and engagement labels
            #   4. Accept the first line that survives all filters
            _SKIP_LABELS = {
                # Engagement labels
                "like", "play", "comment", "share", "ctr", "save", "view",
                # Industry / category filters from TikTok UI
                "beauty", "fashion", "health", "wellness", "food", "beverage",
                "lifestyle", "education", "ecommerce", "e-commerce", "gaming",
                "auto", "automotive", "technology", "tech", "finance", "fintech",
                "travel", "hospitality", "real estate", "retail", "fmcg",
                "personal care", "household", "pets", "sports", "fitness",
                "entertainment", "media", "apparel", "accessories",
                # TikTok UI strings
                "top ads", "trending", "for you", "see more", "watch now",
                "show details", "see details", "view details", "popular",
                "all", "filter", "sort by", "industry",
                # PH-specific
                "philippines", "ph", "manila", "metro manila",
            }
            advertiser = ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            # 1. Look for @-handles first
            for line in lines[:12]:
                if line.startswith("@") and 2 <= len(line) <= 50:
                    advertiser = line
                    break

            # 2. Fallback: first non-skip non-numeric line that looks like a name
            if not advertiser:
                for line in lines[:12]:
                    l_low = line.lower()
                    if l_low in _SKIP_LABELS:
                        continue
                    # Skip engagement labels (Like 1.2K, Play 3M)
                    if re.match(r"^(like|play|comment|share|ctr)\b", l_low):
                        continue
                    # Skip pure numbers (1.2K, 234, 4.5%)
                    if re.match(r"^[\d.,]+\s*[KMB%]?$", line):
                        continue
                    # Skip duration (0:15, 00:30)
                    if re.match(r"^\d{1,2}:\d{2}$", line):
                        continue
                    # Skip very short or very long
                    if len(line) < 3 or len(line) > 60:
                        continue
                    # Skip lines that are mostly digits + symbols
                    if sum(c.isalpha() for c in line) < 3:
                        continue
                    advertiser = line
                    break

            thumbnail_url = ""
            try:
                img = card.locator("img").first
                src = img.get_attribute("src") or ""
                if src.startswith("http"):
                    thumbnail_url = src
            except Exception:
                pass

            ads.append({
                "ad_id": ad_id,
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "country": "PH",
                "advertiser": advertiser[:120],
                "raw_text": text[:1500],
                "likes": likes,
                "plays": plays,
                "ctr": ctr,
                "duration_seconds": duration_s,
                "thumbnail_url": thumbnail_url[:500],
                "detail_url": detail_url[:500] if detail_url else "",
            })

            if len(ads) >= max_ads:
                break
        except Exception:
            continue
    return ads


def scrape_top_ads(country: str = "PH", period: int = 7, niche: str = "all",
                    max_ads: int = 60, scroll_rounds: int = 10, headless: bool = True) -> list[dict]:
    industry = INDUSTRY_MAP.get(niche, "")
    url = build_url(country=country, period=period, industry=industry)
    log.info("TikTok Top Ads: niche=%s country=%s period=%dd  url=%s", niche, country, period, url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = ctx.new_page()
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            _dismiss_consent(page)
            ads = _scrape_top_ads_page(page, max_ads=max_ads, scroll_rounds=scroll_rounds)
            for a in ads:
                a["industry"] = niche
            log.info("TikTok: parsed %d ads", len(ads))
            return ads
        finally:
            ctx.close()
            browser.close()


def run(niches: list[str], country: str = "PH", period: int = 7,
        max_ads_per_niche: int = 60, headless: bool = True) -> int:
    """Scrape TikTok Top Ads for each niche; persist to DB. Returns total ads stored."""
    import db
    run_id = db.start_run(niches=niches, source="tiktok", notes=f"tiktok top_ads period={period}")
    total = 0
    for niche in niches:
        try:
            ads = scrape_top_ads(country=country, period=period, niche=niche,
                                 max_ads=max_ads_per_niche, headless=headless)
            db.insert_tiktok_ads(run_id, ads)
            total += len(ads)
        except Exception as e:
            log.error("TikTok scrape failed for niche %r: %s", niche, e)
    db.finish_run(run_id, total)
    log.info("TikTok run %d: %d ads stored", run_id, total)
    return total
