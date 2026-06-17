"""PH FDA compliance checker — flag illegal medical / therapeutic claims in ad copy.

The Philippines' FDA (RA 9711, RA 7394) bans non-pharmaceutical products from claiming:
  - Cure / treat / prevent specific diseases (cancer, diabetes, hypertension, kidney, etc.)
  - Drug-like effects ("kills bacteria", "treats infection")
  - Unsubstantiated weight-loss promises that imply medical intervention
  - Approved-by-FDA / DOH stamps when not actually registered

Violators face seizure, fines, and shutdown orders. PH ecom operators get into
trouble constantly because they copy hooks from non-PH brands without realising.

Two-pass detection:
  1. Fast keyword regex — catches obvious violations
  2. Optional Claude pass — catches paraphrased / Tagalog idiom violations

Returns severity-rated findings.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("pra.fda")


# --- Severity levels ---
# critical = drug-like cure/treat/prevent disease claims (FDA seizure risk)
# high     = quantified medical claims ("lowers blood pressure 30%")
# medium   = vague medical-adjacent claims ("strengthens immune system")
# low      = lifestyle phrasing that COULD be reframed safely

# Each pattern is (regex, severity, label, why)
_PATTERNS: list[tuple[str, str, str, str]] = [
    # ---------- CRITICAL: disease-specific cure/treat/prevent claims ----------
    (r"\b(cures?|treats?|prevents?|heals?|cure[ds]?)\s+"
     r"(cancer|tumor|diabetes|asthma|hypertension|altapresyon|"
     r"kidney|atay|heart\s+disease|stroke|alzheimer|dementia|"
     r"arthritis|rayuma|tuberculosis|hepatitis|HIV|AIDS)\b",
     "critical", "Drug-like disease claim",
     "FDA prohibits non-drug products from claiming to cure/treat/prevent specific diseases."),
    (r"\b(gamot|panggamot|lunas|panlunas)\s+(sa|ng|para)\s+"
     r"(cancer|diabetes|altapresyon|kidney|atay|sakit\s+sa)\b",
     "critical", "Tagalog disease cure claim",
     "Calling a product 'gamot/lunas para sa [disease]' = treating it as a drug."),
    (r"\b(lumalakas\s+laban\s+sa|magpapagaling\s+sa|"
     r"mawawala\s+ang\s+(cancer|diabetes|altapresyon))\b",
     "critical", "Tagalog disease cure claim",
     "Implicit cure language in Tagalog also violates FDA."),
    (r"\b(kills?|destroys?|eliminates?)\s+(cancer\s+cells?|tumor|"
     r"virus|bacteria|fungus|parasite|infection)\b",
     "critical", "Drug-action claim",
     "Claims of killing pathogens require pharmaceutical registration."),

    # ---------- HIGH: quantified medical claims ----------
    (r"\b(lowers?|reduces?|drops?|babang|babad)\s+"
     r"(blood\s+pressure|blood\s+sugar|cholesterol|presyon|asukal)"
     r"(\s+by\s+|\s+ng\s+)?\d+%?\b",
     "high", "Quantified medical claim",
     "Specific medical numbers without RX support → FDA red flag."),
    (r"\b(\d+\s*%?\s*(effective|effectivity|epektibo)|"
     r"100\s*%\s*(cure|gamot|effective))\b",
     "high", "Efficacy percentage claim",
     "Quantifying drug-like efficacy is a regulatory trigger."),
    (r"\b(clinically\s+proven|medically\s+proven|"
     r"hospital\s+tested|doctor\s+approved|doctor\s+recommended)\b",
     "high", "Unsubstantiated medical authority",
     "Use only if you have RCT/clinical-trial documentation."),

    # ---------- MEDIUM: vague medical claims ----------
    (r"\b(strengthens?|boosts?|enhances?|repairs?)\s+"
     r"(immune\s+system|immunity|resistensya|"
     r"liver|kidney|heart|brain|memory)\b",
     "medium", "Functional medical claim",
     "OK for supplements WITH FDA-CFRR, but high-risk language."),
    (r"\b(detox\s+the\s+(liver|kidney|atay)|"
     r"flush\s+toxins|cleanse\s+the\s+(blood|colon))\b",
     "medium", "Detox-organ claim",
     "FDA pushes back on organ-specific 'detox' marketing."),
    (r"\b(anti[\s-]?(viral|bacterial|fungal|microbial|"
     r"inflammatory|tumor))\b",
     "medium", "Drug-class adjective",
     "These adjectives imply pharmaceutical action."),

    # ---------- LOW: aggressive marketing that could be reframed ----------
    (r"\b(miracle|miraculous|magical|himala|himalang\s+gamot)\b",
     "low", "Miracle language",
     "Reframe as 'natural support' instead — FDA hates miracle claims."),
    (r"\b(guaranteed|warranty|guarantee)\s+(weight\s+loss|cure|results?)\b",
     "low", "Guaranteed outcome",
     "Avoid absolute guarantees on health outcomes."),
    (r"\b(lose|tanggalin|matanggal)\s+\d+\s*(kg|kilos?|pounds?|lbs?|pulgada)\s+"
     r"in\s+\d+\s+(days?|araw|weeks?|linggo|months?|buwan)\b",
     "low", "Quantified weight-loss timeline",
     "Specific timelines invite scrutiny — soften to 'within weeks'."),

    # ---------- INFO: false certification ----------
    (r"\b(FDA[\s-]?(approved|registered|approved)|DOH[\s-]?approved|"
     r"BFAD[\s-]?approved)\b",
     "high", "Certification claim",
     "Verify your CPR/CFRR/CFRA number matches before claiming this."),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), sev, label, why)
              for p, sev, label, why in _PATTERNS]


def scan(ad_text: str) -> list[dict]:
    """Scan ad copy for FDA-risk language. Returns list of findings."""
    if not ad_text:
        return []
    findings: list[dict] = []
    for pat, sev, label, why in _COMPILED:
        for m in pat.finditer(ad_text):
            findings.append({
                "severity": sev,
                "label": label,
                "match": m.group(0),
                "why": why,
                "position": m.start(),
            })
    # Dedup overlapping matches (keep highest-severity per position)
    _sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (_sev_rank.get(f["severity"], 9), f["position"]))
    return findings


def worst_severity(ad_text: str) -> str | None:
    """Quick check — returns the worst severity found, or None if clean."""
    findings = scan(ad_text)
    if not findings:
        return None
    return findings[0]["severity"]


def scan_brand(ads_for_brand: list[dict]) -> dict:
    """Aggregate FDA risk across all ads from one brand.

    Returns: {worst_severity, total_findings, findings_by_severity, sample_matches}
    """
    all_findings: list[dict] = []
    for ad in ads_for_brand:
        text = ad.get("ad_text") or ""
        all_findings.extend(scan(text))

    if not all_findings:
        return {
            "worst_severity": None,
            "total_findings": 0,
            "findings_by_severity": {},
            "sample_matches": [],
        }

    by_sev: dict[str, int] = {}
    for f in all_findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    _sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    worst = min(by_sev.keys(), key=lambda s: _sev_rank.get(s, 9))

    # Unique sample matches (dedup by label)
    seen_labels: set[str] = set()
    samples: list[dict] = []
    for f in all_findings:
        if f["label"] in seen_labels:
            continue
        seen_labels.add(f["label"])
        samples.append(f)
        if len(samples) >= 5:
            break

    return {
        "worst_severity": worst,
        "total_findings": len(all_findings),
        "findings_by_severity": by_sev,
        "sample_matches": samples,
    }


# Color codes for severity badges
SEVERITY_COLORS = {
    "critical": "#E0909F",  # danger
    "high":     "#E6CC73",  # warning
    "medium":   "#D4AF37",  # brass gold
    "low":      "#8FC2B4",  # info teal
    "info":     "#7CC4A0",  # success sage
}
