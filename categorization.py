"""Category + Sub-Category classifier for PH ecommerce ads.

Layered taxonomy:
    Category (4 top-level intents)
        Sub-Category (specific angle / use case)

Detection is keyword-based on ad text + niche. Fast, deterministic, free.
If you want richer tagging, the LLM classifier (llm_classifier.py) writes
`llm_hook_angle` and `llm_claim_type` columns — those are orthogonal to this.

Returned values are LOWERCASE strings (or None when no signal).
"""
from __future__ import annotations

import re
from typing import Any

# ---- Taxonomy ----
# Each sub-category has:
#   - patterns: regex keywords (case-insensitive) to detect from ad text
#   - niche_match: list of niche values that strongly suggest this sub-cat
#   - parent category

SUB_CATEGORIES = {
    # ============ HEALTH & WELLNESS ============
    "slimming": {
        "category": "Health & Wellness",
        "patterns": [
            r"\b(slim+ing|pampapayat|payat|weight\s*loss|losing\s+weight|"
            r"fat\s*burn|fat\s*loss|burn\s*fat|reduce\s+belly|"
            r"flat\s*tummy|tummy\s*trimmer|diet|appetite|"
            r"matangkad|tumaba|pampataba)\b"
        ],
        "niche_match": ["capsule", "herbal_coffee"],
    },
    "detox": {
        "category": "Health & Wellness",
        "patterns": [
            r"\b(detox|cleanse|purify|paghuhugas|toxins|"
            r"liver\s+cleanse|colon\s*cleanse|tubig\s+ng\s+detox)\b"
        ],
        "niche_match": ["capsule", "oral_drops", "herbal_coffee"],
    },
    "supplements": {
        "category": "Health & Wellness",
        "patterns": [
            r"\b(vitamin|multivitamin|supplement|immune|immunity|"
            r"resistensya|kalusugan|wellness|pampalakas\s+ng\s+katawan|"
            r"ascorbic|collagen|glutathione)\b"
        ],
        "niche_match": ["capsule", "oral_drops"],
    },
    "pain-relief": {
        "category": "Health & Wellness",
        "patterns": [
            r"\b(pain\s*relief|sakit|arthritis|rayuma|sore|"
            r"banat|paltos|kirot|joint\s*pain|muscle\s*pain|"
            r"likod|balikat|tuhod|katol)\b"
        ],
        "niche_match": ["balm", "herbal_oil", "liquid_spray"],
    },
    "diabetes-bp": {
        "category": "Health & Wellness",
        "patterns": [
            r"\b(diabetes|altapresyon|hypertension|high\s+blood|"
            r"asukal\s+sa\s+dugo|blood\s+sugar|insulin|"
            r"cholesterol|presyon|tigang)\b"
        ],
        "niche_match": ["capsule", "herbal_coffee", "oral_drops"],
    },

    # ============ BEAUTY & PERSONAL CARE ============
    "whitening": {
        "category": "Beauty & Personal Care",
        "patterns": [
            r"\b(whitening|pampaputi|maputi|kutis|skin\s+lightening|"
            r"brightening|glow|kinis|kinang|pampakinis|paputi)\b"
        ],
        "niche_match": ["cream", "serum", "oil"],
    },
    "anti-aging": {
        "category": "Beauty & Personal Care",
        "patterns": [
            r"\b(anti[\s-]?aging|wrinkle|kunot|tanda|youthful|"
            r"firming|tighten|sagging|crow.?s\s*feet|"
            r"fine\s*lines|aging|matanda\s+itsura)\b"
        ],
        "niche_match": ["cream", "serum"],
    },
    "acne-pimple": {
        "category": "Beauty & Personal Care",
        "patterns": [
            r"\b(acne|pimple|tagihawat|peklat|blemish|"
            r"breakout|spot\s*treatment|kulugo|whitehead|blackhead)\b"
        ],
        "niche_match": ["cream", "serum", "liquid_spray"],
    },
    "hair-growth": {
        "category": "Beauty & Personal Care",
        "patterns": [
            r"\b(hair\s*growth|hair\s*fall|kalbo|patubo|tubo\s+ng\s+buhok|"
            r"thinning|baldness|biotin|minoxidil|pampakapal\s+ng\s+buhok|"
            r"pampahaba\s+ng\s+buhok|alopecia)\b"
        ],
        "niche_match": ["oil", "serum", "liquid_spray"],
    },
    "skincare-general": {
        "category": "Beauty & Personal Care",
        "patterns": [
            r"\b(moisturizer|hydrate|moisturize|kinis\s+ng\s+balat|"
            r"silky|soft\s+skin|skincare|skin\s*care|complexion|"
            r"pampakinis\s+ng\s+balat)\b"
        ],
        "niche_match": ["cream", "serum", "oil"],
    },

    # ============ FOOD & BEVERAGE ============
    "coffee": {
        "category": "Food & Beverage",
        "patterns": [
            r"\b(coffee|kape|brewed|instant\s*coffee|barako|"
            r"3in1|3-in-1|kapeng\s+\w+|caffeine|espresso|americano)\b"
        ],
        "niche_match": ["coffee", "herbal_coffee"],
    },
    "functional-coffee": {
        "category": "Food & Beverage",
        "patterns": [
            r"\b(herbal\s+coffee|functional\s+coffee|adaptogen|"
            r"mushroom\s+coffee|maca|reishi|ganoderma|cordyceps|"
            r"coffee\s+with|kape\s+na)\b"
        ],
        "niche_match": ["herbal_coffee"],
    },

    # ============ WELLNESS & LIFESTYLE ============
    "aromatherapy": {
        "category": "Wellness & Lifestyle",
        "patterns": [
            r"\b(essential\s*oil|aromatherapy|diffuser|"
            r"calming|relaxing|stress\s+relief|"
            r"lavender|eucalyptus|peppermint|tea\s*tree|"
            r"pampakalma|pampatulog)\b"
        ],
        "niche_match": ["oil", "herbal_oil", "liquid_spray"],
    },
    "massage-balm": {
        "category": "Wellness & Lifestyle",
        "patterns": [
            r"\b(massage|balm|hilot|pampahilot|"
            r"warming|cooling\s+balm|menthol|camphor)\b"
        ],
        "niche_match": ["balm", "oil", "herbal_oil"],
    },
    "oral-care": {
        "category": "Wellness & Lifestyle",
        "patterns": [
            r"\b(oral|mouth|teeth|ngipin|breath|hininga|"
            r"toothpaste|mouthwash|gargle|gum)\b"
        ],
        "niche_match": ["oral_drops", "liquid_spray"],
    },
}

# Reverse map: niche → list of (sub_cat, weight) for fallback when no text patterns match
_NICHE_FALLBACK: dict[str, list[tuple[str, int]]] = {}
for sub_cat, spec in SUB_CATEGORIES.items():
    for niche in spec.get("niche_match", []):
        _NICHE_FALLBACK.setdefault(niche, []).append((sub_cat, 1))


# Compile patterns once
_COMPILED: dict[str, list[re.Pattern]] = {}
for sub_cat, spec in SUB_CATEGORIES.items():
    _COMPILED[sub_cat] = [re.compile(p, re.IGNORECASE) for p in spec.get("patterns", [])]


def classify(ad_text: str, niche: str = "") -> tuple[str | None, str | None]:
    """Return (category, sub_category) for an ad.

    Algorithm:
      1. For each sub-category, score how many pattern matches the text has.
         Multiple matches = higher confidence.
      2. If a niche match exists, give it a small boost.
      3. Pick the highest-scoring sub-cat. Its category becomes the category.
      4. If no patterns match and niche is set, fall back to first niche-mapped
         sub-cat (low confidence but better than None).
      5. Return (None, None) if nothing matches.
    """
    text = (ad_text or "")
    if not text and not niche:
        return (None, None)

    scores: dict[str, int] = {}
    for sub_cat, patterns in _COMPILED.items():
        score = 0
        for pat in patterns:
            matches = pat.findall(text)
            if matches:
                score += len(matches) * 2  # 2 points per text match
        # Niche boost
        spec = SUB_CATEGORIES[sub_cat]
        if niche and niche in spec.get("niche_match", []):
            score += 1
        if score > 0:
            scores[sub_cat] = score

    if scores:
        best_sub = max(scores.items(), key=lambda x: x[1])[0]
        best_cat = SUB_CATEGORIES[best_sub]["category"]
        return (best_cat, best_sub)

    # Fallback: niche → first sub-cat that lists it
    if niche and niche in _NICHE_FALLBACK:
        best_sub = _NICHE_FALLBACK[niche][0][0]
        best_cat = SUB_CATEGORIES[best_sub]["category"]
        return (best_cat, best_sub)

    return (None, None)


def all_categories() -> list[str]:
    """Return sorted list of all unique categories."""
    return sorted({spec["category"] for spec in SUB_CATEGORIES.values()})


def all_sub_categories(category: str | None = None) -> list[str]:
    """Return sorted list of sub-categories, optionally filtered by parent category."""
    if category:
        return sorted(
            sub for sub, spec in SUB_CATEGORIES.items()
            if spec["category"] == category
        )
    return sorted(SUB_CATEGORIES.keys())


def annotate(rows: list[dict]) -> dict[str, dict]:
    """Compute category + sub_category for each row. Returns library_id -> fields."""
    out: dict[str, dict] = {}
    for r in rows:
        lib = r.get("library_id")
        if not lib:
            continue
        cat, sub = classify(r.get("ad_text") or "", r.get("niche") or "")
        out[lib] = {"category": cat, "sub_category": sub}
    return out
