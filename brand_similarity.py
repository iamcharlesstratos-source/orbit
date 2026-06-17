"""Find similar brands within the current run, by niche + landing-page type + hook overlap."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse


_STOP = {
    "the", "and", "for", "with", "your", "our", "you", "are", "this", "that",
    "by", "of", "to", "in", "on", "at", "ang", "ng", "nga", "po", "mga", "para",
    "sa", "na", "ay", "kayo", "natin", "ninyo", "https", "com", "shopee", "lazada",
    "ph", "shp", "ee", "tk", "shop", "now", "buy", "learn", "more", "free", "off",
    "save", "new", "use", "used", "make", "made", "go", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "fb", "facebook", "instagram",
}


_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")


def _phrase_tokens(text: str) -> set[str]:
    """Distinctive words used by this brand (filtered stopwords + URL fragments)."""
    if not text:
        return set()
    return {w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOP}


def _landing_type(url: str) -> str:
    """Classify landing URL into: shopee / lazada / tiktok / own_funnel / fb / other."""
    if not url:
        return "other"
    d = urlparse(url).netloc.lower()
    if "shopee.ph" in d or "shp.ee" in d:
        return "shopee"
    if "lazada." in d:
        return "lazada"
    if "tiktok.com" in d:
        return "tiktok"
    if "facebook.com" in d or "messenger" in d or "fb.com" in d:
        return "fb"
    return "own_funnel"


def _brand_profile(rows: list[dict]) -> dict:
    """Aggregate one brand's profile from its ad rows."""
    if not rows:
        return {}
    niches = Counter(r.get("niche") for r in rows if r.get("niche"))
    landing_types = Counter(_landing_type(r.get("landing_url", "")) for r in rows)
    tokens: set[str] = set()
    for r in rows:
        tokens |= _phrase_tokens(r.get("ad_text", ""))
    max_days = max((r.get("days_running") or 0) for r in rows)
    return {
        "niche": niches.most_common(1)[0][0] if niches else None,
        "landing_type": landing_types.most_common(1)[0][0] if landing_types else "other",
        "tokens": tokens,
        "max_days": max_days,
        "ad_count": len(rows),
    }


def find_similar(
    target_brand: str,
    all_rows: list[dict],
    top_n: int = 3,
) -> list[dict]:
    """Score every other brand by similarity to target_brand, return top N.

    Scoring:
      +50  same niche
      +20  same landing-page type (Shopee/Lazada/own funnel/FB)
      +5   per shared distinctive hook word (max +30)
      +15  similar days_running bucket (within 50% of target)
    """
    # Group rows by brand
    by_brand: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        b = (r.get("brand") or r.get("page_name") or "").strip()
        if not b:
            continue
        if not r.get("is_active"):
            continue
        by_brand[b].append(r)

    target_rows = by_brand.get(target_brand, [])
    if not target_rows:
        return []
    target = _brand_profile(target_rows)
    if not target:
        return []

    scored: list[tuple[float, str, dict, list[str]]] = []
    for brand, rows in by_brand.items():
        if brand == target_brand:
            continue
        prof = _brand_profile(rows)
        if not prof:
            continue

        score = 0.0
        reasons: list[str] = []

        if prof["niche"] == target["niche"]:
            score += 50
            reasons.append(f"same niche ({prof['niche']})")

        if prof["landing_type"] == target["landing_type"]:
            score += 20
            reasons.append(f"same landing ({prof['landing_type']})")

        shared = target["tokens"] & prof["tokens"]
        if shared:
            tok_score = min(len(shared) * 5, 30)
            score += tok_score
            top_shared = sorted(shared, key=lambda x: -len(x))[:3]
            reasons.append(f"{len(shared)} shared hook words ({', '.join(top_shared)})")

        if target["max_days"] > 0 and prof["max_days"] > 0:
            ratio = min(target["max_days"], prof["max_days"]) / max(target["max_days"], prof["max_days"])
            if ratio >= 0.5:
                score += 15
                reasons.append(f"similar longevity ({prof['max_days']}d vs {target['max_days']}d)")

        if score > 0:
            scored.append((score, brand, prof, reasons))

    scored.sort(key=lambda x: -x[0])
    return [
        {
            "brand": brand,
            "score": round(score, 1),
            "niche": prof.get("niche"),
            "landing_type": prof.get("landing_type"),
            "max_days": prof.get("max_days"),
            "ad_count": prof.get("ad_count"),
            "reasons": reasons,
        }
        for score, brand, prof, reasons in scored[:top_n]
    ]
