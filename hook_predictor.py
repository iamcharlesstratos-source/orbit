"""Hook performance predictor — estimate longevity for new ad copy.

Trains a simple lightweight model on (hook phrases → days_running) from your DB.
No sklearn dep — uses TF-IDF-style scoring with hand-rolled math.

Model:
  1. Extract 2-3-grams from each ad's text (only PH-confident, in-niche, active)
  2. Compute per-ngram avg days_running + count
  3. Score new copy = sum of avg_days for each known ngram present
  4. Normalize against ngram-count to avoid bias toward longer text

Returns a predicted-longevity tier:
  - "Strong" (predicted 90+ days)
  - "Decent" (30-89 days)
  - "Weak"   (under 30 days, or no signal)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


_TOKEN_RE = re.compile(r"[a-zA-Zà-ü]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "this", "that", "have", "has",
    "from", "are", "was", "but", "not", "all", "any", "can", "will", "our",
    "ang", "ng", "sa", "ay", "para", "ito", "na", "mga", "ka", "mo", "ko",
    "yan", "naman", "lang", "po", "din", "kasi", "kaya", "pero", "nga",
}


def _ngrams(text: str, n_range=(2, 3)) -> list[str]:
    if not text:
        return []
    tokens = [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]
    out: list[str] = []
    for n in range(n_range[0], n_range[1] + 1):
        for i in range(len(tokens) - n + 1):
            out.append(" ".join(tokens[i:i + n]))
    return out


def train_from_rows(rows: list[dict],
                    min_count: int = 2,
                    require_ph_confident: bool = True,
                    require_in_niche: bool = True) -> dict[str, dict]:
    """Build the ngram -> {avg_days, count} model from ad rows.

    Args:
        rows: ad dicts with ad_text + days_running + geo_signal + niche_relevance
        min_count: drop ngrams that appear in fewer than N ads (noise filter)
        require_ph_confident: only train on PH-confident ads
        require_in_niche: only train on in-niche ads

    Returns: {ngram: {avg_days, count}} — empty if not enough data
    """
    days_by_ngram: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if require_ph_confident and r.get("geo_signal") != "ph-confident":
            continue
        if require_in_niche and r.get("niche_relevance") == "no_match":
            continue
        if not r.get("is_active"):
            # We want ads that ARE active — losing ads add noise
            continue
        days = r.get("days_running") or 0
        if days <= 0:
            continue
        seen_this_ad: set[str] = set()
        for ng in _ngrams(r.get("ad_text") or ""):
            if ng in seen_this_ad:
                continue
            seen_this_ad.add(ng)
            days_by_ngram[ng].append(days)

    model: dict[str, dict] = {}
    for ng, days_list in days_by_ngram.items():
        if len(days_list) < min_count:
            continue
        model[ng] = {
            "avg_days": sum(days_list) / len(days_list),
            "count": len(days_list),
            "max_days": max(days_list),
        }
    return model


def predict(copy_text: str, model: dict[str, dict]) -> dict[str, Any]:
    """Score new copy against the trained model.

    Returns:
        {
            predicted_days: float,  # weighted average days
            tier: 'Strong' | 'Decent' | 'Weak',
            matched_ngrams: [(ngram, avg_days, count), ...],
            n_matches: int,
            confidence: 'high' | 'medium' | 'low'
        }
    """
    if not model or not copy_text:
        return {
            "predicted_days": 0,
            "tier": "Weak",
            "matched_ngrams": [],
            "n_matches": 0,
            "confidence": "low",
        }
    text_ngrams = _ngrams(copy_text)
    matched = []
    for ng in set(text_ngrams):
        if ng in model:
            m = model[ng]
            matched.append((ng, m["avg_days"], m["count"]))

    if not matched:
        return {
            "predicted_days": 0,
            "tier": "Weak",
            "matched_ngrams": [],
            "n_matches": 0,
            "confidence": "low",
        }

    # Weighted average: ngrams with more occurrences carry more weight
    total_weight = sum(c for _, _, c in matched)
    weighted_days = sum(d * c for _, d, c in matched) / total_weight if total_weight else 0

    # Tier classification
    if weighted_days >= 90:
        tier = "Strong"
    elif weighted_days >= 30:
        tier = "Decent"
    else:
        tier = "Weak"

    # Confidence: how many distinct matches + total count
    if len(matched) >= 5 and total_weight >= 15:
        confidence = "high"
    elif len(matched) >= 2 and total_weight >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    # Sort matched by avg_days desc
    matched.sort(key=lambda x: -x[1])

    return {
        "predicted_days": round(weighted_days, 1),
        "tier": tier,
        "matched_ngrams": matched[:10],  # top 10 contributors
        "n_matches": len(matched),
        "confidence": confidence,
    }
