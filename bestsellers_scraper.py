"""Shopee + Lazada + TikTok Shop bestseller-list scrapers.

Pulls top-selling products per niche/category, NOT just ads. Different signal
than the ad library — these are products people are actually buying NOW.

Bestseller URLs (last known good as of 2025):
  Shopee PH:     https://shopee.ph/search?keyword=<kw>&sortBy=sales&order=desc
  Lazada PH:     https://www.lazada.com.ph/catalog/?q=<kw>&sort=salesdesc
  TikTok Shop:   not easily browseable without login; sniped via search

Returns standardized records ready to insert into our marketplace_bestsellers table.

WARNING: PH marketplaces aggressively rate-limit + bot-detect. Playwright with
stealth is mandatory. Sometimes blocks anyway — accept partial results.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

log = logging.getLogger("pra.bestsellers")


# ---- DB schema for storing bestseller snapshots ----
BESTSELLERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bestsellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,           -- 'shopee' | 'lazada' | 'tiktok_shop'
    snapshot_date TEXT NOT NULL,      -- YYYY-MM-DD
    niche TEXT,
    keyword TEXT,
    rank INTEGER,
    product_name TEXT,
    product_url TEXT,
    price_php REAL,
    units_sold INTEGER,
    rating REAL,
    review_count INTEGER,
    shop_name TEXT,
    thumbnail_url TEXT,
    raw_blob TEXT
);
CREATE INDEX IF NOT EXISTS idx_bestsellers_date ON bestsellers(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_bestsellers_niche ON bestsellers(niche);
CREATE INDEX IF NOT EXISTS idx_bestsellers_platform ON bestsellers(platform);
"""


def _to_int_kmag(s: str) -> int:
    """'1.2k' -> 1200, '3.4M' -> 3400000, '234' -> 234, '' -> 0."""
    if not s:
        return 0
    s = s.replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*([KMB]?)", s, re.IGNORECASE)
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


def scrape_shopee_bestsellers(keyword: str, max_results: int = 30,
                              headless: bool = True,
                              timeout_ms: int = 30000) -> list[dict]:
    """Scrape Shopee PH bestseller list for a keyword (sorted by sales desc)."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    url = f"https://shopee.ph/search?keyword={quote_plus(keyword)}&sortBy=sales&order=desc"
    out: list[dict] = []
    snap_date = datetime.now().date().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless,
                                     args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="en-PH",
        )
        try:
            from playwright_stealth import Stealth
            page = ctx.new_page()
            try:
                Stealth().apply_stealth_sync(page)
            except Exception:
                pass
        except ImportError:
            page = ctx.new_page()

        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            # Try a few item-container selectors (Shopee rotates them)
            cards = []
            for sel in ("div[data-sqe='item']", ".shopee-search-item-result__item",
                        "[class*='product']"):
                cards = page.locator(sel).all()
                if len(cards) >= 5:
                    break
            for i, card in enumerate(cards[:max_results]):
                try:
                    text = card.inner_text(timeout=2000)
                    if not text or len(text) < 20:
                        continue
                    # Extract fields heuristically
                    title = ""
                    for line in text.splitlines()[:4]:
                        line = line.strip()
                        if line and not line.startswith("₱") and len(line) > 10:
                            title = line[:200]
                            break
                    price = 0.0
                    price_m = re.search(r"₱\s?([\d,]+(?:\.\d+)?)", text)
                    if price_m:
                        try:
                            price = float(price_m.group(1).replace(",", ""))
                        except ValueError:
                            pass
                    sold = 0
                    sold_m = re.search(r"([\d.,]+\s*[Kk]?)\+?\s*sold", text, re.IGNORECASE)
                    if sold_m:
                        sold = _to_int_kmag(sold_m.group(1))
                    href = ""
                    try:
                        a = card.locator("a").first
                        href = a.get_attribute("href") or ""
                        if href and href.startswith("/"):
                            href = "https://shopee.ph" + href
                    except Exception:
                        pass
                    thumb = ""
                    try:
                        img = card.locator("img").first
                        thumb = img.get_attribute("src") or ""
                    except Exception:
                        pass
                    if title:
                        out.append({
                            "platform": "shopee",
                            "snapshot_date": snap_date,
                            "keyword": keyword,
                            "rank": i + 1,
                            "product_name": title,
                            "product_url": href[:500],
                            "price_php": price,
                            "units_sold": sold,
                            "rating": None,
                            "review_count": 0,
                            "shop_name": "",
                            "thumbnail_url": thumb[:500],
                        })
                except Exception:
                    continue
            log.info("Shopee bestsellers '%s': parsed %d products", keyword, len(out))
        except PWTimeout:
            log.warning("Shopee timeout for keyword %r", keyword)
        finally:
            ctx.close()
            browser.close()

    return out


def scrape_lazada_bestsellers(keyword: str, max_results: int = 30,
                              headless: bool = True,
                              timeout_ms: int = 30000) -> list[dict]:
    """Scrape Lazada PH bestseller list."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    url = f"https://www.lazada.com.ph/catalog/?q={quote_plus(keyword)}&sort=salesdesc"
    out: list[dict] = []
    snap_date = datetime.now().date().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless,
                                     args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="en-PH",
        )
        try:
            from playwright_stealth import Stealth
            page = ctx.new_page()
            try:
                Stealth().apply_stealth_sync(page)
            except Exception:
                pass
        except ImportError:
            page = ctx.new_page()

        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            cards = []
            for sel in ("[data-qa-locator='product-item']",
                        ".gridItem--Yd0sa", ".Bm3ON",
                        "div[class*='product']"):
                cards = page.locator(sel).all()
                if len(cards) >= 5:
                    break
            for i, card in enumerate(cards[:max_results]):
                try:
                    text = card.inner_text(timeout=2000)
                    if not text or len(text) < 20:
                        continue
                    title = ""
                    for line in text.splitlines()[:4]:
                        line = line.strip()
                        if line and not line.startswith("₱") and len(line) > 10:
                            title = line[:200]
                            break
                    price = 0.0
                    price_m = re.search(r"₱\s?([\d,]+(?:\.\d+)?)", text)
                    if price_m:
                        try:
                            price = float(price_m.group(1).replace(",", ""))
                        except ValueError:
                            pass
                    sold = 0
                    sold_m = re.search(r"([\d.,]+\s*[Kk]?)\+?\s*sold", text, re.IGNORECASE)
                    if sold_m:
                        sold = _to_int_kmag(sold_m.group(1))
                    href = ""
                    try:
                        a = card.locator("a").first
                        href = a.get_attribute("href") or ""
                        if href.startswith("//"):
                            href = "https:" + href
                    except Exception:
                        pass
                    thumb = ""
                    try:
                        img = card.locator("img").first
                        thumb = img.get_attribute("src") or ""
                        if thumb.startswith("//"):
                            thumb = "https:" + thumb
                    except Exception:
                        pass
                    if title:
                        out.append({
                            "platform": "lazada",
                            "snapshot_date": snap_date,
                            "keyword": keyword,
                            "rank": i + 1,
                            "product_name": title,
                            "product_url": href[:500],
                            "price_php": price,
                            "units_sold": sold,
                            "rating": None,
                            "review_count": 0,
                            "shop_name": "",
                            "thumbnail_url": thumb[:500],
                        })
                except Exception:
                    continue
            log.info("Lazada bestsellers '%s': parsed %d products", keyword, len(out))
        except PWTimeout:
            log.warning("Lazada timeout for keyword %r", keyword)
        finally:
            ctx.close()
            browser.close()

    return out


def scrape_tiktok_shop_bestsellers(keyword: str, max_results: int = 30,
                                    headless: bool = True) -> list[dict]:
    """TikTok Shop bestsellers — VERY rate-limited, often blocked.

    Tries the Discover/Shop page. If TikTok bans, returns empty list.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    url = f"https://shop.tiktok.com/view/search?keyword={quote_plus(keyword)}"
    out: list[dict] = []
    snap_date = datetime.now().date().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless,
                                     args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 900},
            locale="en-PH",
        )
        page = ctx.new_page()
        try:
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            cards = page.locator("[data-e2e='product-card'], [class*='product-card']").all()
            for i, card in enumerate(cards[:max_results]):
                try:
                    text = card.inner_text(timeout=2000)
                    if not text:
                        continue
                    title = next(
                        (l.strip() for l in text.splitlines()
                         if len(l.strip()) > 10 and not l.startswith("₱")),
                        "",
                    )[:200]
                    price = 0.0
                    pm = re.search(r"₱\s?([\d,]+(?:\.\d+)?)", text)
                    if pm:
                        try:
                            price = float(pm.group(1).replace(",", ""))
                        except ValueError:
                            pass
                    sold = 0
                    sm = re.search(r"([\d.,]+\s*[Kk]?)\+?\s*sold", text, re.IGNORECASE)
                    if sm:
                        sold = _to_int_kmag(sm.group(1))
                    if title:
                        out.append({
                            "platform": "tiktok_shop",
                            "snapshot_date": snap_date,
                            "keyword": keyword,
                            "rank": i + 1,
                            "product_name": title,
                            "product_url": "",
                            "price_php": price,
                            "units_sold": sold,
                            "rating": None,
                            "review_count": 0,
                            "shop_name": "",
                            "thumbnail_url": "",
                        })
                except Exception:
                    continue
            log.info("TikTok Shop '%s': parsed %d products", keyword, len(out))
        except PWTimeout:
            log.warning("TikTok Shop timeout for keyword %r", keyword)
        finally:
            ctx.close()
            browser.close()

    return out


def scrape_all(keywords: list[str], niche: str = "",
               platforms: list[str] | None = None,
               max_per_platform: int = 20,
               headless: bool = True) -> list[dict]:
    """Run all bestseller scrapers for the given keywords.

    Returns a flat list of records with niche attached, ready to insert into DB.
    """
    platforms = platforms or ["shopee", "lazada"]  # TikTok Shop is risky default
    all_records: list[dict] = []
    for kw in keywords:
        if "shopee" in platforms:
            try:
                rows = scrape_shopee_bestsellers(kw, max_results=max_per_platform,
                                                  headless=headless)
                for r in rows:
                    r["niche"] = niche or ""
                all_records.extend(rows)
            except Exception as e:
                log.error("Shopee scrape failed for %r: %s", kw, e)
        if "lazada" in platforms:
            try:
                rows = scrape_lazada_bestsellers(kw, max_results=max_per_platform,
                                                  headless=headless)
                for r in rows:
                    r["niche"] = niche or ""
                all_records.extend(rows)
            except Exception as e:
                log.error("Lazada scrape failed for %r: %s", kw, e)
        if "tiktok_shop" in platforms:
            try:
                rows = scrape_tiktok_shop_bestsellers(kw, max_results=max_per_platform,
                                                       headless=headless)
                for r in rows:
                    r["niche"] = niche or ""
                all_records.extend(rows)
            except Exception as e:
                log.error("TikTok Shop scrape failed for %r: %s", kw, e)
    return all_records
