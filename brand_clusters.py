"""Brand cluster detection — find brands likely run by the same operator.

PH ecommerce operators often run multiple "brand names" off the same playbook:
- Same landing domain (Shopee/Lazada store)
- Same hook patterns / ad text style
- Same niche + same target audience
- Same supplier (1688 photo style)

This module clusters brands by behavioural fingerprint so the user can
"unmask" multi-brand operators and treat them as one entity.

Algorithm (simple, deterministic):
1. Build a feature vector per brand: top hook bigrams, landing domain, niche
2. Compare every brand pair via Jaccard similarity on the feature set
3. Group brands whose similarity > threshold into clusters
4. Return clusters as list of brand-name groups
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("pra.clusters")


_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "this", "that", "have", "has",
    "from", "are", "was", "but", "not", "all", "any", "can", "will", "our",
    "ang", "ng", "sa", "ay", "para", "ito", "na", "mga", "ka", "mo", "ko",
    "yan", "naman", "lang", "po", "din", "kasi", "kaya", "pero", "nga",
}


def _domain_of(url: str) -> str:
    """Extract bare domain (e.g. 'shopee.ph/shop/123' → 'shopee.ph')."""
    if not url:
        return ""
    try:
        d = urlparse(url).netloc.lower().replace("www.", "")
        return d
    except Exception:
        return ""


def _tokenize(text: str) -> list[str]:
    """Lower-case word tokenizer, strips punctuation, drops stopwords + short tokens."""
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Zàáâäéêëèíîïóôöòúûüùñ]{3,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _brand_fingerprint(ads: list[dict]) -> set[str]:
    """Build a feature set (Jaccard-comparable) for one brand from its ads.

    Features added (each becomes a string in the set):
        - dom:shopee.ph/store123        (landing domain + first path segment)
        - niche:cream
        - bigram:before_after           (top 8 bigrams)
        - hook:para_payat
    """
    features: set[str] = set()
    for ad in ads:
        url = ad.get("landing_url") or ""
        dom = _domain_of(url)
        if dom:
            features.add(f"dom:{dom}")
            # Add path's first segment (often the store/shop ID)
            try:
                path = urlparse(url).path.strip("/").split("/")[0][:40]
                if path:
                    features.add(f"path:{dom}/{path}")
            except Exception:
                pass
        if ad.get("niche"):
            features.add(f"niche:{ad['niche']}")

    # Bigrams from all ad text — keep top 8
    all_tokens: list[str] = []
    for ad in ads:
        all_tokens.extend(_tokenize(ad.get("ad_text") or ""))
    if len(all_tokens) >= 2:
        bigrams = [f"{a}_{b}" for a, b in zip(all_tokens, all_tokens[1:])]
        for bg, _cnt in Counter(bigrams).most_common(8):
            features.add(f"bigram:{bg}")

    return features


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def find_clusters(rows: list[dict], threshold: float = 0.35,
                  min_brand_ads: int = 2) -> list[dict]:
    """Cluster brands from the given ads list.

    Args:
        rows: ads with at least brand/page_name, landing_url, niche, ad_text
        threshold: Jaccard similarity >= this groups brands into a cluster
        min_brand_ads: ignore brands with fewer ads than this (noise filter)

    Returns:
        List of cluster dicts:
        [
            {
                "brands": ["Glow Lab", "GlowLab PH", "Glow Studio"],
                "size": 3,
                "shared_features": ["dom:shopee.ph/glow_studio", "niche:cream"],
                "lead_brand": "Glow Lab",   # the one with most ads
            },
            ...
        ]
        Only clusters with size >= 2 are returned.
    """
    if not rows:
        return []

    # Group ads by brand
    by_brand: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        b = (r.get("brand") or r.get("page_name") or "").strip()
        if not b:
            continue
        by_brand[b].append(r)

    # Filter low-volume brands
    brand_names = [b for b, ads in by_brand.items() if len(ads) >= min_brand_ads]
    if len(brand_names) < 2:
        return []

    # Build fingerprints
    fp: dict[str, set[str]] = {b: _brand_fingerprint(by_brand[b]) for b in brand_names}

    # Compute pairwise similarities, build union-find clusters
    parent: dict[str, str] = {b: b for b in brand_names}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for i, b1 in enumerate(brand_names):
        for b2 in brand_names[i + 1:]:
            sim = _jaccard(fp[b1], fp[b2])
            if sim >= threshold:
                _union(b1, b2)

    # Collect groups
    groups: dict[str, list[str]] = defaultdict(list)
    for b in brand_names:
        groups[_find(b)].append(b)

    clusters: list[dict] = []
    for _root, members in groups.items():
        if len(members) < 2:
            continue
        # Sort members by ad count (lead = most ads)
        members_sorted = sorted(members, key=lambda b: -len(by_brand[b]))
        shared = fp[members_sorted[0]].copy()
        for m in members_sorted[1:]:
            shared &= fp[m]
        clusters.append({
            "brands": members_sorted,
            "size": len(members_sorted),
            "shared_features": sorted(shared)[:8],
            "lead_brand": members_sorted[0],
            "total_ads": sum(len(by_brand[b]) for b in members_sorted),
        })

    # Largest clusters first
    clusters.sort(key=lambda c: -c["size"])
    return clusters
