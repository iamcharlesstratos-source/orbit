"""Anomaly detection — flag interesting between-run changes.

Surfaces events for the notification inbox. No false-positive theatre — only
fires on real signal:

  - Brand surge: brand added >= 5 NEW active variants since prev run
  - Brand retired: brand went from N active variants to 0
  - Watchlist drop: starred brand went inactive (was active in prev run)
  - Niche cold: niche lost >= 30% of its active brands
  - First-time crosser: brand crossed 90-day longevity for the first time

Returns plain list of dicts ready for the inbox renderer.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def detect(prev_rows: list[dict], curr_rows: list[dict],
           starred_brands: set[str] | None = None) -> list[dict]:
    """Compute anomalies between two runs.

    Returns: list of event dicts {icon, type, title, detail, brand?}
    sorted by severity (positive surges first, then retirements, then niche cold).
    """
    if not prev_rows or not curr_rows:
        return []
    starred = starred_brands or set()
    starred_low = {b.lower() for b in starred}

    # Bucket ads by brand for both runs
    def _brand_buckets(rows: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = defaultdict(lambda: {
            "active_ids": set(), "total": 0, "max_days": 0, "niche": ""
        })
        for r in rows:
            b = (r.get("brand") or r.get("page_name") or "").strip()
            if not b:
                continue
            entry = out[b]
            entry["total"] += 1
            if r.get("is_active"):
                entry["active_ids"].add(r.get("library_id"))
            entry["max_days"] = max(entry["max_days"], r.get("days_running") or 0)
            if not entry["niche"]:
                entry["niche"] = r.get("niche") or ""
        return dict(out)

    prev_b = _brand_buckets(prev_rows)
    curr_b = _brand_buckets(curr_rows)

    events: list[dict] = []

    # ---- Brand surges (>=5 new active variants) ----
    for brand, c in curr_b.items():
        p = prev_b.get(brand)
        if not p:
            # Brand-new brand — flag if launches with >= 3 active ads
            n_new = len(c["active_ids"])
            if n_new >= 3:
                events.append({
                    "icon": "🚀", "type": "positive", "brand": brand,
                    "title": f"{brand} launched with {n_new} ads",
                    "detail": f"New brand in {c['niche']} niche. Worth investigating early.",
                })
            continue
        n_new = len(c["active_ids"] - p["active_ids"])
        if n_new >= 5:
            events.append({
                "icon": "⚡", "type": "accent", "brand": brand,
                "title": f"{brand} is scaling",
                "detail": f"+{n_new} new active variants since previous run. "
                          f"Now running {len(c['active_ids'])} ads in {c['niche']}.",
            })

    # ---- Brand retirements (went from N>0 to 0 active) ----
    for brand, p in prev_b.items():
        if not p["active_ids"]:
            continue
        c = curr_b.get(brand)
        if c is None or len(c["active_ids"]) == 0:
            events.append({
                "icon": "🪦", "type": "warning", "brand": brand,
                "title": f"{brand} went dark",
                "detail": f"Had {len(p['active_ids'])} active ads previously; now 0. "
                          f"Possibly retired or rebranded.",
            })

    # ---- Watchlist drops ----
    for brand_low in starred_low:
        # Find the case-correct version
        brand_orig = next(
            (b for b in (curr_b.keys() | prev_b.keys()) if b.lower() == brand_low),
            brand_low,
        )
        p = prev_b.get(brand_orig)
        c = curr_b.get(brand_orig)
        if p and p["active_ids"] and (c is None or not c["active_ids"]):
            events.append({
                "icon": "★", "type": "warning", "brand": brand_orig,
                "title": f"★ Watchlist: {brand_orig} went dark",
                "detail": "A brand you're tracking has no active ads in the latest run.",
            })

    # ---- 90-day milestone crossings ----
    for brand, c in curr_b.items():
        p = prev_b.get(brand)
        if not p:
            continue
        if p["max_days"] < 90 <= c["max_days"]:
            events.append({
                "icon": "🏆", "type": "positive", "brand": brand,
                "title": f"{brand} crossed 90-day longevity",
                "detail": f"Their longest-running ad just passed the proven-winner threshold "
                          f"({c['max_days']:,} days). Strong signal.",
            })

    # ---- Niche cold (>= 30% drop in active brands) ----
    def _niche_active_count(buckets: dict[str, dict]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for b, entry in buckets.items():
            if entry["active_ids"] and entry["niche"]:
                out[entry["niche"]] += 1
        return dict(out)
    prev_nc = _niche_active_count(prev_b)
    curr_nc = _niche_active_count(curr_b)
    for niche, prev_count in prev_nc.items():
        curr_count = curr_nc.get(niche, 0)
        if prev_count >= 5 and curr_count <= prev_count * 0.7:
            pct = round((1 - curr_count / prev_count) * 100)
            events.append({
                "icon": "❄", "type": "warning",
                "title": f"{niche} niche cooling",
                "detail": f"Active brands dropped {pct}% "
                          f"({prev_count} → {curr_count}). Competition may be retreating.",
            })

    # Sort: positives first, then watchlist drops, then warnings, then niche cold
    _priority = {"positive": 0, "accent": 1, "warning": 2, "info": 3}
    events.sort(key=lambda e: _priority.get(e.get("type", "info"), 9))
    return events
