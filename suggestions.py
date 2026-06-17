"""Rule-based 'what to do today' recommendations from the DB.

Each rule produces zero or more Suggestion objects. The app displays them
in priority order with emoji and a short action description.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import db


@dataclass
class Suggestion:
    icon: str
    priority: int           # higher = more urgent / valuable
    title: str
    detail: str
    related: list[dict] = field(default_factory=list)  # ads/brands referenced


def _ads_by_brand(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        b = (r.get("brand") or r.get("page_name") or "").strip()
        if b:
            out[b].append(r)
    return out


def proven_winners(latest_rows: list[dict], min_days: int = 180) -> list[Suggestion]:
    by_brand = _ads_by_brand(latest_rows)
    out: list[Suggestion] = []
    for brand, ads in by_brand.items():
        active = [a for a in ads if a.get("is_active")]
        if not active:
            continue
        max_days = max((a.get("days_running") or 0) for a in active)
        if max_days < min_days:
            continue
        sample = max(active, key=lambda a: a.get("days_running") or 0)
        out.append(Suggestion(
            icon="🏆",
            priority=min(200 + max_days // 30, 320),
            title=f"PROVEN WINNER: {brand} ({max_days} days active)",
            detail=(
                f"{len(active)} active ads in '{sample.get('niche')}'. "
                f"Their longest ad has been running over {max_days // 30} months — "
                f"that's the strongest signal of profitability you'll get without insider data. "
                f"Reverse-engineer the angle in '{(sample.get('ad_text') or '')[:140]}...'"
            ),
            related=[sample],
        ))
    return sorted(out, key=lambda s: -s.priority)[:10]


def heavy_testers(latest_rows: list[dict], min_variants: int = 5) -> list[Suggestion]:
    by_brand = _ads_by_brand(latest_rows)
    out: list[Suggestion] = []
    for brand, ads in by_brand.items():
        active = [a for a in ads if a.get("is_active")]
        if len(active) < min_variants:
            continue
        sample = max(active, key=lambda a: a.get("days_running") or 0)
        out.append(Suggestion(
            icon="🎯",
            priority=50 + len(active),
            title=f"HEAVY TESTER: {brand} ({len(active)} variants live)",
            detail=(
                f"Running {len(active)} simultaneous variants in '{sample.get('niche')}'. "
                f"Brands that test this hard are almost always profitable — "
                f"the one variant they double down on is the proven hook."
            ),
            related=[sample],
        ))
    return sorted(out, key=lambda s: -s.priority)[:8]


def new_winners_since(prev_rows: list[dict], curr_rows: list[dict], threshold_days: int = 30) -> list[Suggestion]:
    """Ads that cross the 30-day threshold between two runs — newly proven.

    Skips this rule if the two runs aren't comparable in scope (e.g. partial scrapes),
    which would otherwise mark every ad as 'new'.
    """
    if not prev_rows or not curr_rows:
        return []
    if len(prev_rows) < max(50, len(curr_rows) // 2):
        return []  # previous run was a partial scrape — comparison would be misleading

    prev_ids = {r.get("library_id"): r for r in prev_rows}
    seen_brand: set[str] = set()
    out: list[Suggestion] = []
    candidates = []
    for r in curr_rows:
        if not r.get("is_active"):
            continue
        days = r.get("days_running") or 0
        if days < threshold_days:
            continue
        prev = prev_ids.get(r.get("library_id"))
        if prev is None:
            continue  # ad wasn't in previous run; can't claim it 'crossed' anything
        if (prev.get("days_running") or 0) >= threshold_days:
            continue  # was already past threshold last run
        candidates.append(r)

    for r in sorted(candidates, key=lambda x: -(x.get("days_running") or 0)):
        brand = r.get("brand") or r.get("page_name") or "?"
        if brand in seen_brand:
            continue
        seen_brand.add(brand)
        days = r.get("days_running") or 0
        out.append(Suggestion(
            icon="🔥",
            priority=min(80 + days, 199),
            title=f"NEW WINNER: {brand} just crossed {threshold_days} days",
            detail=(
                f"Niche: {r.get('niche')}. Ad: '{(r.get('ad_text') or '')[:160]}...' "
                f"Crossing {threshold_days} days while staying active is the moment a funnel proves itself — "
                f"these are the trending winners going up, before they're obvious."
            ),
            related=[r],
        ))
    return out[:10]


def retired_ads(prev_rows: list[dict], curr_rows: list[dict]) -> list[Suggestion]:
    """Ads from the previous run that disappeared — 'what stopped working'."""
    curr_ids = {r.get("library_id") for r in curr_rows}
    out: list[Suggestion] = []
    by_brand_retired: dict[str, list[dict]] = defaultdict(list)
    for r in prev_rows:
        if not r.get("is_active"):
            continue
        if r.get("library_id") not in curr_ids:
            by_brand_retired[r.get("brand") or r.get("page_name") or "?"].append(r)
    for brand, ads in by_brand_retired.items():
        if len(ads) < 2:  # noise floor — at least 2 retirements to flag
            continue
        sample = max(ads, key=lambda a: a.get("days_running") or 0)
        out.append(Suggestion(
            icon="💀",
            priority=40 + len(ads),
            title=f"RETIRED: {brand} stopped {len(ads)} ads",
            detail=(
                f"Niche: {sample.get('niche')}. Their longest stopped ad ran {sample.get('days_running')} days. "
                f"Could mean: new offer launching (good signal), or these failed (avoid the angle)."
            ),
            related=[sample],
        ))
    return sorted(out, key=lambda s: -s.priority)[:8]


def niche_competition(latest_rows: list[dict]) -> list[Suggestion]:
    """Brand counts per niche — saturation indicator."""
    by_niche: dict[str, set[str]] = defaultdict(set)
    for r in latest_rows:
        n = r.get("niche")
        b = r.get("brand") or r.get("page_name")
        if n and b and r.get("is_active"):
            by_niche[n].add(b)
    out: list[Suggestion] = []
    sorted_niches = sorted(by_niche.items(), key=lambda x: -len(x[1]))
    if sorted_niches:
        crowded = sorted_niches[0]
        out.append(Suggestion(
            icon="📊",
            priority=30,
            title=f"NICHE HEAT: '{crowded[0]}' has {len(crowded[1])} active brands",
            detail=(
                f"Most competitive niche today. Either differentiate hard or target the long-tail "
                f"keywords (e.g., specific ingredients) rather than the head term."
            ),
        ))
        if len(sorted_niches) > 1:
            quiet = sorted_niches[-1]
            out.append(Suggestion(
                icon="🌱",
                priority=28,
                title=f"OPPORTUNITY: '{quiet[0]}' has only {len(quiet[1])} active brands",
                detail=(
                    f"Lightest competition of your tracked niches. Often means either an under-served "
                    f"market (good) or no demand (verify on Shopee before betting)."
                ),
            ))
    return out


def landing_url_intelligence(latest_rows: list[dict]) -> list[Suggestion]:
    """Distribution of where winners are sending traffic."""
    own_funnel = 0
    shopee = 0
    lazada = 0
    tiktok = 0
    fb_only = 0
    for r in latest_rows:
        if not r.get("is_active") or (r.get("days_running") or 0) < 90:
            continue
        url = (r.get("landing_url") or "").lower()
        if not url:
            continue
        if "shopee." in url or "shp.ee" in url:
            shopee += 1
        elif "lazada." in url:
            lazada += 1
        elif "tiktok." in url:
            tiktok += 1
        elif "facebook.com" in url or "messenger" in url:
            fb_only += 1
        else:
            own_funnel += 1
    total = own_funnel + shopee + lazada + tiktok + fb_only
    if total < 5:
        return []
    pct_funnel = round(100 * own_funnel / total)
    pct_shopee = round(100 * shopee / total)
    return [Suggestion(
        icon="🧭",
        priority=20,
        title=f"WHERE THE WINNERS SEND TRAFFIC (90+ day ads)",
        detail=(
            f"{pct_funnel}% own funnels  •  {pct_shopee}% Shopee  •  "
            f"{round(100*lazada/total)}% Lazada  •  {round(100*tiktok/total)}% TikTok  •  "
            f"{round(100*fb_only/total)}% FB/Messenger only. "
            f"Own-funnel-heavy = serious scalers; Shopee-heavy = quick-validation play."
        ),
    )]


def generate(top_n: int = 20) -> list[Suggestion]:
    """Run all rules over the latest DB state and return prioritised suggestions."""
    db.init_db()
    latest = db.latest_run_id(only_meta=True)
    if not latest:
        return []
    curr = db.ads_for_run(latest)

    runs = db.list_runs(limit=2, only_meta=True)
    prev_rows: list[dict] = []
    if len(runs) >= 2:
        prev_rows = db.ads_for_run(runs[1]["run_id"])

    out: list[Suggestion] = []
    out.extend(proven_winners(curr))
    out.extend(heavy_testers(curr))
    if prev_rows:
        out.extend(new_winners_since(prev_rows, curr))
        out.extend(retired_ads(prev_rows, curr))
    out.extend(niche_competition(curr))
    out.extend(landing_url_intelligence(curr))
    return sorted(out, key=lambda s: -s.priority)[:top_n]
