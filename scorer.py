"""Rank ads by winning-potential. PH Meta ads don't expose spend/reach,
so we lean on longevity + active flag + how many variants the same page is running."""
from __future__ import annotations

import re
from collections import defaultdict


_COMMON_TOKENS = {
    # generic business / location words that shouldn't anchor a brand match
    "the", "and", "for", "with", "your", "our", "you", "are", "this", "that",
    "by", "of", "to", "in", "on", "ph", "philippines", "filipino", "pinoy",
    "official", "shop", "store", "trading", "enterprise", "enterprises",
    "manufacturing", "manufacturer", "co", "inc", "corp", "company", "global",
    "international", "world", "club", "group", "ltd", "team", "house",
    # marketing words common to GoNutrients-style sister pages
    "negosyo", "tayo", "dream", "business", "businesses", "ideas", "idea",
    "ceo", "become", "becomes", "becoming", "start", "new", "now", "best",
    "buy", "online", "free", "real", "premium", "quality", "from", "more",
}


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z]{3,}", name.lower()) if t not in _COMMON_TOKENS}


def cluster_pages(page_names: list[str]) -> dict[str, str]:
    """Group page names that share any distinctive token. Returns name -> canonical brand."""
    unique = list(dict.fromkeys(p for p in page_names if p))
    parent = {p: p for p in unique}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    token_map = {p: _tokens(p) for p in unique}
    for i, a in enumerate(unique):
        if not token_map[a]:
            continue
        for b in unique[i + 1:]:
            if token_map[a] & token_map[b]:
                union(a, b)

    groups: dict[str, list[str]] = defaultdict(list)
    for p in unique:
        groups[find(p)].append(p)

    mapping: dict[str, str] = {}
    for members in groups.values():
        canonical = min(members, key=lambda x: (len(x), x))
        for m in members:
            mapping[m] = canonical
    return mapping


def score_ad(days_running: int, is_active: bool, variants_for_page: int) -> float:
    base = days_running * (1.5 if is_active else 1.0)
    variant_bonus = min(max(variants_for_page - 1, 0), 10) * 5
    return round(base + variant_bonus, 2)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct)
    return sorted_values[min(idx, len(sorted_values) - 1)]


def _niche_day_caps(ads: list[dict], pct: float = 0.95) -> dict[str, float]:
    """Per-niche 95th-percentile days_running. Used to clip outliers from off-region ads."""
    by_niche: dict[str, list[float]] = defaultdict(list)
    for a in ads:
        n = a.get("niche") or "_"
        d = a.get("days_running") or 0
        if d > 0:
            by_niche[n].append(d)
    caps: dict[str, float] = {}
    for niche, vals in by_niche.items():
        vals.sort()
        caps[niche] = _percentile(vals, pct)
    return caps


def rank_ads(ads: list[dict]) -> list[dict]:
    brand_map = cluster_pages([a.get("page_name", "") for a in ads])
    brand_counts: dict[str, int] = defaultdict(int)
    for a in ads:
        brand = brand_map.get(a.get("page_name", ""), a.get("page_name", ""))
        a["brand"] = brand
        if brand:
            brand_counts[brand] += 1

    caps = _niche_day_caps(ads, pct=0.95)

    for a in ads:
        variants = brand_counts.get(a.get("brand", ""), 1)
        a["variants_from_brand"] = variants
        raw_days = int(a.get("days_running") or 0)
        cap = caps.get(a.get("niche") or "_", raw_days)
        capped_days = min(raw_days, int(cap)) if cap > 0 else raw_days
        a["score"] = score_ad(
            days_running=raw_days,
            is_active=bool(a.get("is_active")),
            variants_for_page=variants,
        )
        a["score_normalized"] = score_ad(
            days_running=capped_days,
            is_active=bool(a.get("is_active")),
            variants_for_page=variants,
        )
    return sorted(ads, key=lambda x: x["score_normalized"], reverse=True)


def top_products(ads: list[dict], top_n: int = 30) -> list[dict]:
    """Aggregate ads by clustered brand — strongest advertisers, not strongest single ads."""
    by_brand: dict[str, dict] = {}
    for a in ads:
        brand = a.get("brand") or a.get("page_name") or "(unknown)"
        entry = by_brand.setdefault(brand, {
            "brand": brand,
            "niche": a.get("niche", ""),
            "page_names": set(),
            "ad_count": 0,
            "total_score": 0.0,
            "max_days_running": 0,
            "any_active": False,
            "sample_ad_text": "",
            "sample_landing_url": "",
        })
        entry["page_names"].add(a.get("page_name", ""))
        entry["ad_count"] += 1
        entry["total_score"] = round(entry["total_score"] + float(a.get("score", 0)), 2)
        entry["max_days_running"] = max(entry["max_days_running"], int(a.get("days_running") or 0))
        entry["any_active"] = entry["any_active"] or bool(a.get("is_active"))
        if not entry["sample_ad_text"] and a.get("ad_text"):
            entry["sample_ad_text"] = a["ad_text"][:300]
        if not entry["sample_landing_url"] and a.get("landing_url"):
            entry["sample_landing_url"] = a["landing_url"]

    for entry in by_brand.values():
        entry["page_names"] = ", ".join(sorted(n for n in entry["page_names"] if n))

    return sorted(by_brand.values(), key=lambda x: x["total_score"], reverse=True)[:top_n]
