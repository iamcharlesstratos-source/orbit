"""Off-niche pollution detection — geo confidence + niche-keyword relevance.

Run after scrape to tag every ad row with:
  geo_signal     - 'ph-confident' | 'ph-likely' | 'unknown'
  niche_relevance - 'match' | 'no_match'

The app can filter on these; they don't drop ads outright (avoids false negatives).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


# Niche -> required-keyword anchors. An ad text containing ANY of these is "in niche".
NICHE_KEYWORDS: dict[str, list[str]] = {
    "capsule": [
        "capsule", "cap.", "tablet", "supplement", "pill", "softgel",
        "vitamin", "probiotic", "collagen", "glutathione", "garcinia",
    ],
    "cream": [
        "cream", "lotion", "moisturizer", "moisturiser", "balm",
        "skincare", "whitening", "anti-aging", "anti aging", "rejuven",
        "soap", "skin", "face wash", "facial",
    ],
    "oil": [
        "essential oil", "hair oil", "body oil", "scalp oil", "massage oil",
        "coconut oil", "argan oil", "rosehip", "jojoba", "ginger oil",
        "treatment oil",
    ],
    "coffee": [
        "coffee", "brew", "caffeine", "barako", "espresso", "latte",
        "kape", "java", "beans",
    ],
    "balm": [
        "balm", "vapor rub", "vaporub", "white flower", "efficascent",
        "katinko", "muscle pain", "pain relief", "salonpas", "tiger balm",
        "linimento", "mainit", "ginhawa",
    ],
    "herbal_oil": [
        "herbal oil", "lagundi", "tawa tawa", "tawa-tawa", "lemongrass",
        "tanglad", "oregano oil", "ginger oil", "luya", "lana",
        "essential oil", "ayurveda",
    ],
    "oral_drops": [
        "drops", "oral drops", "vitamin drops", "immunity drops",
        "kids drops", "infant", "baby drops", "tincture", "patak",
        "iron drops", "zinc drops",
    ],
    "herbal_coffee": [
        "herbal coffee", "ganoderma", "lingzhi", "reishi", "moringa coffee",
        "malunggay coffee", "mushroom coffee", "stand-up pouch", "stand up pouch",
        "coffee mix", "kape herbal",
    ],
    "serum": [
        "serum", "face serum", "vitamin c serum", "hyaluronic", "niacinamide",
        "retinol", "skin serum", "hair serum", "growth serum", "ampoule",
        "essence",
    ],
    "liquid_spray": [
        "spray", "throat spray", "nasal spray", "antiseptic spray",
        "wound spray", "anti bacterial", "antibacterial", "disinfectant",
        "lugol", "iodine spray", "oxygen spray",
    ],
}

# Known non-PH brands that occasionally leak through ph-likely scoring
# (e.g. their PH affiliate has Tagalog markers but the actual brand is US/elsewhere)
KNOWN_NON_PH_BRANDS = {
    "glow up",
    "wild growth",
    "adrienne's classic desserts",
    "scarlet car accessories",
    "perfectmatch low-carb",
    "perfect match low-carb",
    "perfectmatch low-carb selections",
    "giga",
    "peter paul philippine corporation",  # actually local but listing is suspicious
}


def is_blocked_brand(brand: str) -> bool:
    """Returns True if brand matches our blocklist of confirmed non-PH operators."""
    if not brand:
        return False
    b = brand.lower().strip()
    return any(blocked in b for blocked in KNOWN_NON_PH_BRANDS)


# Filipino/Tagalog filler words that suggest PH-targeted copy
_TAGALOG_MARKERS = re.compile(
    r"\b(ang|nga|po|mga|para|ako|kayo|natin|ninyo|nila|naman|lang|sino|kasi|pwede|sana|hindi|pinas|pilipinas|filipino|filipina|pinoy|pinay)\b",
    re.IGNORECASE,
)

# Phase 11.4 — explicit non-PH TLDs (penalize landing pages that target other markets)
_FOREIGN_TLDS = (
    ".com.au", ".com.my", ".com.sg", ".com.id", ".com.vn", ".com.th",
    ".co.uk", ".co.in", ".co.id", ".co.nz", ".co.za", ".co.kr", ".co.jp",
    ".ca", ".au", ".my", ".sg", ".vn", ".th", ".id", ".us",
    ".uk", ".de", ".fr", ".es", ".it", ".nl", ".se", ".no", ".dk",
)

# Phase 11.4 — foreign currency mentions (USD/AUD/MYR/etc. in text = NOT PH)
_FOREIGN_CURRENCY = re.compile(
    r"(?:\$\s?\d|USD\s?\d|US\$|AUD\s?\d|A\$|MYR\s?\d|RM\s?\d|SGD\s?\d|S\$|"
    r"THB\s?\d|฿\s?\d|VND\s?\d|₫\s?\d|IDR\s?\d|Rp\s?\d|"
    r"GBP\s?\d|£\s?\d|EUR\s?\d|€\s?\d|JPY\s?\d|¥\s?\d|"
    r"\d+\s?(?:USD|GBP|AUD|EUR|MYR|SGD|THB|VND|IDR)\b)",
    re.IGNORECASE,
)

# Phase 11.4 — foreign-market keywords that imply non-PH targeting
_FOREIGN_KEYWORDS = re.compile(
    r"\b(?:singapore|malaysia|thailand|indonesia|vietnam|australia|"
    r"new zealand|united kingdom|canada|usa|united states|"
    r"jakarta|kuala lumpur|bangkok|sydney|melbourne|toronto|"
    r"shipping to (?!ph|philippines)|delivery to (?!ph|philippines))\b",
    re.IGNORECASE,
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def detect_geo(landing_url: str, ad_text: str, brand: str = "") -> str:
    """Score PH-targeting signals and return one of: non-ph, ph-confident, ph-likely, unknown.

    Phase 11.4 changes: tighter ph-confident criteria (require strong signal),
    plus active penalties for foreign-market signals.
    """
    # First check the known-non-PH blocklist — explicit override
    if brand and is_blocked_brand(brand):
        return "non-ph"

    url = (landing_url or "").lower()
    text = ad_text or ""
    text_low = text.lower()
    score = 0

    dom = _domain(url)

    # ---- Strong PH signals (positive) ----
    has_ph_marketplace = any(d in dom for d in ("shopee.ph", "shp.ee", "lazada.com.ph"))
    has_ph_tld = dom.endswith(".ph") or ".ph/" in url
    has_peso = "₱" in text
    has_ph_text = (
        "philippines" in text_low or "pilipinas" in text_low or
        " ph " in text_low or "manila" in text_low or "cebu" in text_low or
        "davao" in text_low
    )
    has_tagalog = bool(_TAGALOG_MARKERS.search(text))

    if has_ph_marketplace:
        score += 3
    if has_ph_tld and not has_ph_marketplace:
        score += 2
    if has_peso:
        score += 2
    if has_ph_text:
        score += 1
    if has_tagalog:
        score += 1

    # ---- Strong non-PH signals (negative) ----
    has_foreign_tld = any(dom.endswith(tld) for tld in _FOREIGN_TLDS) and not has_ph_tld
    has_foreign_currency = bool(_FOREIGN_CURRENCY.search(text))
    has_foreign_keyword = bool(_FOREIGN_KEYWORDS.search(text))

    if has_foreign_tld:
        score -= 3
    if has_foreign_currency:
        score -= 2
    if has_foreign_keyword:
        score -= 2

    # Generic .com without any PH signal
    is_generic_com = (
        dom.endswith(".com") and
        not has_ph_marketplace and not has_ph_tld and
        ".ph" not in url
    )
    if is_generic_com and not (has_peso or has_ph_text or has_tagalog):
        score -= 2

    # ---- Verdict ----
    # ph-confident now requires score >= 3 (was 2) — tighter to reduce false positives.
    # Need at least ONE strong positive signal (marketplace, TLD, peso) for confidence.
    has_strong_positive = has_ph_marketplace or has_ph_tld or has_peso
    if score >= 3 and has_strong_positive:
        return "ph-confident"
    if score >= 2 and (has_strong_positive or has_tagalog):
        return "ph-likely"
    if score >= 1 and has_tagalog:
        return "ph-likely"
    # Need two negative signals OR explicit foreign TLD/currency to flag non-ph.
    if score <= -3 or has_foreign_tld or has_foreign_currency or has_foreign_keyword:
        return "non-ph"
    return "unknown"


def detect_niche_relevance(niche: str, ad_text: str, keyword: str = "") -> str:
    """Does the ad text actually mention the niche? Search keyword is excluded by design —
    we want to verify the AD itself talks about the niche, not just trust the search query."""
    kws = NICHE_KEYWORDS.get(niche, [])
    if not kws:
        return "match"
    hay = (ad_text or "").lower()
    if not hay.strip():
        return "unknown"
    for kw in kws:
        if kw.lower() in hay:
            return "match"
    return "no_match"


def annotate(rows: list[dict]) -> dict[str, dict]:
    """Compute geo_signal and niche_relevance for each row. Returns library_id -> fields."""
    out: dict[str, dict] = {}
    for r in rows:
        lib = r.get("library_id")
        if not lib:
            continue
        brand = r.get("brand") or r.get("page_name") or ""
        out[lib] = {
            "geo_signal": detect_geo(
                r.get("landing_url") or "", r.get("ad_text") or "", brand,
            ),
            "niche_relevance": detect_niche_relevance(
                r.get("niche") or "", r.get("ad_text") or ""
            ),
        }
    return out
