"""PH location detector — parse ad text and landing URLs for Philippine geo signals.

Returns location strings like:
    "Metro Manila"  "Cebu"  "Davao"  "Luzon"  "Visayas"  "Mindanao"  "PH-wide"

Multiple locations possible; we return the most specific one detected.
If nothing matched but the ad is PH-confident (geo_signal), default is "PH-wide".
"""
from __future__ import annotations

import re

# Specific cities + their normalized output label
# Order matters — more specific first (Quezon City before "Manila" alone)
_CITY_PATTERNS = [
    # ---- Metro Manila + NCR cities ----
    (re.compile(r"\b(metro\s+manila|metromanila|ncr|national\s+capital)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(quezon\s*city|q\.?\s*c\.?|QC)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(makati|bgc|bonifacio\s+global\s+city|taguig|fort\s+bonifacio)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(pasig|mandaluyong|ortigas|san\s+juan|marikina)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(pasay|paranaque|las\s+pinas|muntinlupa|alabang)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(caloocan|malabon|navotas|valenzuela)\b", re.IGNORECASE), "Metro Manila"),
    (re.compile(r"\b(manila|maynila)\b", re.IGNORECASE), "Metro Manila"),

    # ---- Major Luzon provinces / cities ----
    (re.compile(r"\b(cavite|dasmarinas|imus|bacoor|tagaytay)\b", re.IGNORECASE), "Cavite"),
    (re.compile(r"\b(laguna|santa\s+rosa|calamba|los\s+banos)\b", re.IGNORECASE), "Laguna"),
    (re.compile(r"\b(batangas|lipa\s+city|tanauan)\b", re.IGNORECASE), "Batangas"),
    (re.compile(r"\b(rizal|antipolo|cainta|taytay)\b", re.IGNORECASE), "Rizal"),
    (re.compile(r"\b(bulacan|malolos|meycauayan)\b", re.IGNORECASE), "Bulacan"),
    (re.compile(r"\b(pampanga|angeles\s+city|san\s+fernando)\b", re.IGNORECASE), "Pampanga"),
    (re.compile(r"\b(nueva\s+ecija|cabanatuan|gapan)\b", re.IGNORECASE), "Nueva Ecija"),
    (re.compile(r"\b(baguio|benguet|la\s+trinidad)\b", re.IGNORECASE), "Baguio"),
    (re.compile(r"\b(pangasinan|dagupan|urdaneta)\b", re.IGNORECASE), "Pangasinan"),
    (re.compile(r"\b(la\s+union|san\s+fernando\s+la\s+union)\b", re.IGNORECASE), "La Union"),
    (re.compile(r"\b(ilocos|laoag|vigan)\b", re.IGNORECASE), "Ilocos"),
    (re.compile(r"\b(bicol|legazpi|naga|albay|sorsogon|camarines)\b", re.IGNORECASE), "Bicol"),

    # ---- Visayas ----
    (re.compile(r"\b(cebu\s*city|cebu)\b", re.IGNORECASE), "Cebu"),
    (re.compile(r"\b(iloilo|jaro|molo)\b", re.IGNORECASE), "Iloilo"),
    (re.compile(r"\b(bacolod|negros\s+occidental)\b", re.IGNORECASE), "Bacolod"),
    (re.compile(r"\b(tacloban|leyte|samar)\b", re.IGNORECASE), "Tacloban / Leyte"),
    (re.compile(r"\b(dumaguete|negros\s+oriental)\b", re.IGNORECASE), "Dumaguete"),
    (re.compile(r"\b(boracay|aklan|kalibo)\b", re.IGNORECASE), "Aklan / Boracay"),

    # ---- Mindanao ----
    (re.compile(r"\b(davao\s*city|davao)\b", re.IGNORECASE), "Davao"),
    (re.compile(r"\b(cagayan\s+de\s+oro|cdo|misamis\s+oriental)\b", re.IGNORECASE), "Cagayan de Oro"),
    (re.compile(r"\b(zamboanga|zambo)\b", re.IGNORECASE), "Zamboanga"),
    (re.compile(r"\b(general\s+santos|gensan|sarangani)\b", re.IGNORECASE), "General Santos"),
    (re.compile(r"\b(butuan|agusan)\b", re.IGNORECASE), "Butuan"),
    (re.compile(r"\b(iligan|lanao)\b", re.IGNORECASE), "Iligan"),
    (re.compile(r"\b(cotabato|maguindanao)\b", re.IGNORECASE), "Cotabato"),
]

# Broader regions (fallback if no city matched)
_REGION_PATTERNS = [
    (re.compile(r"\b(luzon)\b", re.IGNORECASE), "Luzon"),
    (re.compile(r"\b(visayas|visayan|cebuano)\b", re.IGNORECASE), "Visayas"),
    (re.compile(r"\b(mindanao|min\s+da\s+nao)\b", re.IGNORECASE), "Mindanao"),
]

# Phrases that suggest nationwide / no specific location
_NATIONWIDE_PATTERNS = [
    re.compile(r"\b(nationwide|nation-?wide|all\s+over\s+the\s+philippines|"
               r"buong\s+pilipinas|whole\s+ph|ph[\s-]+wide|"
               r"available\s+nationwide|deliver\s+nationwide|"
               r"shipping\s+nationwide|lbc|j&t|jrs|2go)\b", re.IGNORECASE),
]


def detect_location(ad_text: str, landing_url: str = "") -> str | None:
    """Return the most-specific PH location detected, or None.

    Priority:
      1. Specific city / province match (e.g. "Metro Manila", "Cebu")
      2. Region match (Luzon / Visayas / Mindanao)
      3. Nationwide phrase → "PH-wide"
      4. None — no signal
    """
    text_blob = f"{ad_text or ''} {landing_url or ''}"
    if not text_blob.strip():
        return None
    # Normalize hyphens/underscores/slashes in URL slugs to spaces so
    # "quezon-city-shop" matches the "quezon city" pattern.
    text_blob = text_blob.replace("-", " ").replace("_", " ").replace("/", " ")

    # 1. Specific city — return first match
    for pat, label in _CITY_PATTERNS:
        if pat.search(text_blob):
            return label

    # 2. Broader region
    for pat, label in _REGION_PATTERNS:
        if pat.search(text_blob):
            return label

    # 3. Nationwide phrase
    for pat in _NATIONWIDE_PATTERNS:
        if pat.search(text_blob):
            return "PH-wide"

    return None


# Pre-sorted unique list of all output labels (for sidebar filter dropdown)
ALL_LOCATIONS = sorted({label for _, label in _CITY_PATTERNS} |
                       {label for _, label in _REGION_PATTERNS} |
                       {"PH-wide"})


def annotate(rows: list[dict]) -> dict[str, dict]:
    """Compute location for each row. Returns library_id -> {location}."""
    out: dict[str, dict] = {}
    for r in rows:
        lib = r.get("library_id")
        if not lib:
            continue
        loc = detect_location(r.get("ad_text") or "", r.get("landing_url") or "")
        # If still none AND ad is PH-confident, default to PH-wide
        if loc is None and r.get("geo_signal") == "ph-confident":
            loc = "PH-wide"
        out[lib] = {"location": loc}
    return out
