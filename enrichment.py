"""Marketplace enrichment — price, sold, rating, review_count from Shopee & Lazada.

Bridges 'ads people run' to 'products people actually buy'.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

log = logging.getLogger("pra.enrichment")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_SHOPEE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json",
    "Accept-Language": "en-PH,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://shopee.ph/",
    "Origin": "https://shopee.ph",
    "X-API-SOURCE": "pc",
    "X-Requested-With": "XMLHttpRequest",
    "X-Shopee-Language": "en",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

_SESSIONS: dict[str, requests.Session] = {}


def _shopee_session() -> requests.Session:
    """Reusable session — hits homepage once to grab anti-bot cookies."""
    s = _SESSIONS.get("shopee")
    if s is not None:
        return s
    s = requests.Session()
    s.headers.update(_SHOPEE_HEADERS)
    try:
        s.get("https://shopee.ph/", timeout=10)
    except requests.RequestException:
        pass
    _SESSIONS["shopee"] = s
    return s

_SHOPEE_ID_RE = re.compile(r"-i\.(?P<shop>\d+)\.(?P<item>\d+)")
_SHOPEE_ID_ALT_RE = re.compile(r"/product/(?P<shop>\d+)/(?P<item>\d+)")


def classify_marketplace(url: str) -> str:
    if not url:
        return ""
    dom = urlparse(url).netloc.lower()
    if "shopee.ph" in dom or "shp.ee" in dom:
        return "shopee"
    if "lazada." in dom:
        return "lazada"
    if "tiktok.com" in dom:
        return "tiktok"
    return ""


def _resolve_redirect(url: str, timeout: int = 8) -> str:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers={"User-Agent": _UA})
        return r.url
    except requests.RequestException:
        return url


def _extract_shopee_ids(url: str) -> tuple[str, str] | None:
    m = _SHOPEE_ID_RE.search(url) or _SHOPEE_ID_ALT_RE.search(url)
    if not m:
        return None
    return m.group("shop"), m.group("item")


def enrich_shopee(url: str) -> dict | None:
    if "shp.ee" in url:
        url = _resolve_redirect(url)
    ids = _extract_shopee_ids(url)
    if not ids:
        return None
    shop_id, item_id = ids
    api = f"https://shopee.ph/api/v4/item/get?itemid={item_id}&shopid={shop_id}"
    try:
        sess = _shopee_session()
        r = sess.get(api, timeout=12)
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or {}
        if not data:
            return None
        # Shopee stores price as integer * 100000 (5-decimal fixed point)
        price_raw = data.get("price")
        price = round(price_raw / 100000, 2) if isinstance(price_raw, (int, float)) else None
        rating_block = data.get("item_rating") or {}
        rating = rating_block.get("rating_star")
        rating_count = rating_block.get("rating_count")
        if isinstance(rating_count, list) and rating_count:
            rating_count = rating_count[0]
        return {
            "mp_source": "shopee",
            "mp_currency": "PHP",
            "mp_price": price,
            "mp_sold": data.get("historical_sold") or data.get("global_sold_count"),
            "mp_rating": round(rating, 2) if isinstance(rating, (int, float)) else None,
            "mp_reviews": int(rating_count) if isinstance(rating_count, (int, float)) else None,
            "mp_enriched_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        log.debug("shopee enrichment failed for %s: %s", url, e)
        return None


def enrich_lazada(url: str) -> dict | None:
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-PH"}, timeout=12)
        if r.status_code != 200:
            return None
        html = r.text
        price = None
        m = re.search(r'"price":\s*"?([\d.]+)"?', html)
        if m:
            try:
                price = float(m.group(1))
            except ValueError:
                pass
        rating = None
        m = re.search(r'"ratingScore"\s*:\s*"?([\d.]+)"?', html)
        if m:
            try:
                rating = float(m.group(1))
            except ValueError:
                pass
        reviews = None
        m = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', html)
        if m:
            try:
                reviews = int(m.group(1))
            except ValueError:
                pass
        sold = None
        m = re.search(r'"itemSoldCntShow"\s*:\s*"([\d,kK.]+)"', html)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                if "k" in raw.lower():
                    sold = int(float(raw.lower().replace("k", "")) * 1000)
                else:
                    sold = int(raw)
            except ValueError:
                pass
        if not (price or rating or reviews or sold):
            return None
        return {
            "mp_source": "lazada",
            "mp_currency": "PHP",
            "mp_price": price,
            "mp_sold": sold,
            "mp_rating": rating,
            "mp_reviews": reviews,
            "mp_enriched_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception as e:
        log.debug("lazada enrichment failed for %s: %s", url, e)
        return None


def enrich_one(landing_url: str) -> dict | None:
    mp = classify_marketplace(landing_url)
    if mp == "shopee":
        return enrich_shopee(landing_url)
    if mp == "lazada":
        return enrich_lazada(landing_url)
    return None


def enrich_run(run_id: int, max_workers: int = 6) -> tuple[int, int]:
    """Enrich all unenriched ads in a run via requests-based API.
    Fast but Shopee blocks most API calls now — use enrich_run_browser for reliability.
    Returns (attempted, succeeded)."""
    import concurrent.futures
    import db
    pending = db.ads_needing_enrichment(run_id)
    if not pending:
        log.info("No marketplace URLs to enrich in run %d.", run_id)
        return (0, 0)
    log.info("Enriching %d marketplace URLs (fast/requests mode)...", len(pending))
    succeeded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(enrich_one, r["landing_url"]): r for r in pending}
        for fut in concurrent.futures.as_completed(futs):
            row = futs[fut]
            result = fut.result()
            if result:
                db.update_ad_enrichment(row["library_id"], run_id, result)
                succeeded += 1
    log.info("Enrichment (fast): %d/%d succeeded", succeeded, len(pending))
    if succeeded == 0 and len(pending) > 5:
        log.warning("All API calls blocked — try `python main.py --enrich-browser` for Playwright-based enrichment.")
    return (len(pending), succeeded)


def _parse_kmag(raw: str, full_match: str) -> int | None:
    """Parse '1.2k' / '5.3K' / '150' / '1,234' into int."""
    raw = raw.replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    low = full_match.lower()
    if "m" in low:
        val *= 1_000_000
    elif "k" in low:
        val *= 1_000
    return int(val)


def _parse_shopee_dom_text(text: str) -> dict | None:
    """Extract price, sold, rating, reviews from Shopee product page text.
    Takes max ₱-price found to avoid shipping fees being misread as product price."""
    import re as _re
    out: dict[str, Any] = {}

    # Take the MAX ₱ price visible — product price usually > shipping fee thresholds
    prices = _re.findall(r"₱\s?([\d,]+(?:\.\d+)?)", text)
    parsed_prices = []
    for p in prices:
        try:
            parsed_prices.append(float(p.replace(",", "")))
        except ValueError:
            continue
    if parsed_prices:
        out["mp_price"] = max(parsed_prices)

    # ---- Sold count parsing (Phase 11.2 — multi-pattern fallback) ----
    # Shopee shows units sold in many formats depending on locale + product:
    #   "1.5k sold"   "234 Sold"   "1,234 sold"   "X+ sold"
    #   "Sold: 1234"  "Sold 5,432"  "Already sold 89"  "Bought 250 times"
    sold_values: list[int] = []

    # Pattern A: "<number> sold" — number BEFORE "sold"
    for m in _re.finditer(
        r"([\d.,]+\+?)\s*([KkMm]?)\s*(?:sold|Sold|SOLD)\b",
        text,
    ):
        raw = m.group(1).rstrip("+")
        suffix = m.group(2)
        val = _parse_kmag(raw, raw + suffix)
        if val is not None and val > 0:
            sold_values.append(val)

    # Pattern B: "Sold <number>" / "Sold: <number>" / "Already sold <number>"
    # — number AFTER "sold" (with optional colon or "already" prefix)
    for m in _re.finditer(
        r"(?:Already\s+sold|Total\s+Sold|Items\s+Sold|Sold)\s*[:：]?\s*([\d.,]+\+?)\s*([KkMm]?)",
        text,
        flags=_re.IGNORECASE,
    ):
        raw = m.group(1).rstrip("+")
        suffix = m.group(2)
        val = _parse_kmag(raw, raw + suffix)
        if val is not None and val > 0:
            sold_values.append(val)

    # Pattern C: "Bought X times" / "Purchased X" — common on PH Shopee
    for m in _re.finditer(
        r"(?:Bought|Purchased)\s+([\d.,]+\+?)\s*([KkMm]?)\s*(?:times|x)?",
        text,
    ):
        raw = m.group(1).rstrip("+")
        suffix = m.group(2)
        val = _parse_kmag(raw, raw + suffix)
        if val is not None and val > 0:
            sold_values.append(val)

    if sold_values:
        # Use max — biggest plausible figure is the cumulative total.
        # (Shopee sometimes shows "234 sold (last 24h)" alongside cumulative "5k sold".)
        out["mp_sold"] = max(sold_values)

    # Rating patterns
    for pat in (r"(\d\.\d)\s*/?\s*5(?:\s*stars?)?", r"(\d\.\d)\s+(?:Product\s+)?Ratings?", r"(\d\.\d)\s+out of 5"):
        m = _re.search(pat, text)
        if m:
            try:
                rv = float(m.group(1))
                if 0 < rv <= 5:
                    out["mp_rating"] = rv
                    break
            except ValueError:
                continue

    # Reviews count
    reviews_m = _re.search(r"([\d.,]+)\s?([Kk]?)\s+(?:Ratings?|Reviews?)\b", text)
    if reviews_m:
        v = _parse_kmag(reviews_m.group(1), reviews_m.group(1) + reviews_m.group(2))
        if v is not None:
            out["mp_reviews"] = v

    if not out:
        return None
    out["mp_source"] = "shopee"
    out["mp_currency"] = "PHP"
    out["mp_enriched_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def _parse_lazada_dom_text(text: str) -> dict | None:
    import re as _re
    out: dict[str, Any] = {}

    prices = _re.findall(r"₱\s?([\d,]+(?:\.\d+)?)", text)
    parsed_prices = []
    for p in prices:
        try:
            parsed_prices.append(float(p.replace(",", "")))
        except ValueError:
            continue
    if parsed_prices:
        out["mp_price"] = max(parsed_prices)

    for pat in (r"(\d\.\d)\s*/\s*5", r"(\d\.\d)\s+Ratings?", r"Rating\s*:\s*(\d\.\d)"):
        m = _re.search(pat, text)
        if m:
            try:
                rv = float(m.group(1))
                if 0 < rv <= 5:
                    out["mp_rating"] = rv
                    break
            except ValueError:
                continue

    sold_matches = _re.findall(r"([\d.,]+)\s?([Kk]?)\s+[Ss]old", text)
    sold_values = []
    for raw, suffix in sold_matches:
        val = _parse_kmag(raw, raw + suffix)
        if val is not None and val > 0:
            sold_values.append(val)
    if sold_values:
        out["mp_sold"] = max(sold_values)

    if not out:
        return None
    out["mp_source"] = "lazada"
    out["mp_currency"] = "PHP"
    out["mp_enriched_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def enrich_run_browser(run_id: int, max_ads: int = 80, timeout_per_ad_s: int = 15) -> tuple[int, int]:
    """Browser-based enrichment using Playwright. Slow but reliable.
    Caps at max_ads (default 80) — top-scoring rows are enriched first."""
    import db
    from playwright.sync_api import sync_playwright

    pending_all = db.ads_needing_enrichment(run_id)
    if not pending_all:
        log.info("No marketplace URLs to enrich in run %d.", run_id)
        return (0, 0)
    # Filter to product URLs only (skip shop URLs that don't have product IDs)
    pending = []
    seen_products: set[str] = set()
    for r in pending_all:
        url = r["landing_url"]
        mp = classify_marketplace(url)
        if mp == "shopee":
            ids = _extract_shopee_ids(url)
            if not ids and "shp.ee" not in url:
                continue
            key = f"shopee:{':'.join(ids)}" if ids else f"shopee:{url}"
        elif mp == "lazada":
            key = f"lazada:{url[:100]}"
        else:
            continue
        if key in seen_products:
            continue
        seen_products.add(key)
        pending.append(r)
    pending.sort(key=lambda r: -(r.get("score_normalized") or r.get("score") or 0))
    pending = pending[:max_ads]
    log.info("Browser enrichment: %d unique products (capped at %d)...", len(pending), max_ads)

    succeeded = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=_UA,
            locale="en-PH",
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.new_page()
        for i, row in enumerate(pending, 1):
            url = row["landing_url"]
            mp = classify_marketplace(url)
            try:
                page.goto(url, timeout=timeout_per_ad_s * 1000, wait_until="domcontentloaded")
                # Wait for client-side rendered content (Shopee/Lazada are SPAs)
                try:
                    page.wait_for_selector("text=/₱/", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                body_text = page.locator("body").inner_text(timeout=4000)
                if mp == "shopee":
                    parsed = _parse_shopee_dom_text(body_text)
                else:
                    parsed = _parse_lazada_dom_text(body_text)
                if parsed:
                    db.update_ad_enrichment(row["library_id"], run_id, parsed)
                    succeeded += 1
                    if i % 10 == 0:
                        log.info("  ... %d/%d processed, %d enriched so far", i, len(pending), succeeded)
            except Exception as e:
                log.debug("browser enrich failed for %s: %s", url, e)
        browser.close()
    log.info("Browser enrichment: %d/%d succeeded", succeeded, len(pending))
    return (len(pending), succeeded)
