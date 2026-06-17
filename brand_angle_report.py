"""AI-generated 'why this brand wins' reports via Claude.

Takes a brand's ads + DB metadata and produces a 1-paragraph analyst report:
  - Winning angle (problem-solution, social-proof, etc.)
  - Target demographic
  - Top hook patterns
  - Supplier / sourcing hints
  - Recommended next moves

Cost: ~$0.01-0.03 per report. Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("pra.angle")


SYSTEM_PROMPT = """You are a senior performance-marketing analyst with 10+ years
working PH ecommerce brands across Shopee, Lazada, TikTok Shop, and Meta. Your
job: read a brand's ad data and produce ONE crisp analyst report that an
operator can act on in 5 minutes.

Structure your report as exactly these sections (use the headings verbatim):

### Winning angle
2-3 sentences describing the dominant emotional + functional angle this brand
runs. What problem do they hook on? What outcome do they sell?

### Target demographic
The specific PH audience they're going after — age range, gender skew,
lifestyle signals, region if detectable. 2 sentences max.

### Top hook patterns
Bullet list of 3-5 specific phrases or framings they use repeatedly. Quote
their actual words. Include both English and Tagalog/Taglish phrases.

### Likely supplier signal
If their ads suggest a specific supplier origin (1688 generic, white-label PH
manufacturer, branded import), note it. If unclear, say so.

### Recommended next moves for an operator copying this playbook
3 specific actions a PH operator should take to test a similar product:
1. Sourcing
2. Creative
3. Audience targeting

KEEP TOTAL UNDER 300 WORDS. Bold the most important phrase in each section.
No fluff. No corporate language. Talk like a PH operator advising another."""


def generate(brand: str, ads: list[dict], brand_meta: dict | None = None,
             model: str = "claude-haiku-4-5",
             api_key: str | None = None) -> dict[str, Any]:
    """Generate an angle report for a brand.

    Args:
        brand: brand name
        ads: list of ad dicts (typically all ads for this brand)
        brand_meta: optional dict with niche, max_days_running, ad_count, etc.

    Returns: {ok, report_markdown, error, ads_used}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "ok": False, "report_markdown": "",
            "error": "ANTHROPIC_API_KEY env var not set.",
            "ads_used": 0,
        }
    try:
        import anthropic
    except ImportError:
        return {
            "ok": False, "report_markdown": "",
            "error": "anthropic SDK not installed.",
            "ads_used": 0,
        }
    if not ads:
        return {
            "ok": False, "report_markdown": "",
            "error": "No ads provided.",
            "ads_used": 0,
        }

    # Curate the top ads to send (avoid sending 50+ duplicate variants)
    # Take the 8 longest-running active ads + 3 oldest (for context)
    sorted_active = sorted(
        [a for a in ads if a.get("is_active")],
        key=lambda a: -(a.get("days_running") or 0),
    )[:8]
    sorted_oldest = sorted(
        ads, key=lambda a: -(a.get("days_running") or 0),
    )[:3]
    sample_ads = sorted_active + [a for a in sorted_oldest if a not in sorted_active][:3]
    sample_ads = sample_ads[:10]

    # Build the user message
    meta_lines = []
    if brand_meta:
        meta_lines.append(f"Brand: {brand}")
        meta_lines.append(f"Niche: {brand_meta.get('niche', '—')}")
        meta_lines.append(f"Active ads count: {brand_meta.get('ad_count', len(ads))}")
        meta_lines.append(f"Max ad longevity: {brand_meta.get('max_days_running', 0)} days")
        if brand_meta.get("category"):
            meta_lines.append(f"Category: {brand_meta['category']}")
        if brand_meta.get("location"):
            meta_lines.append(f"Detected location: {brand_meta['location']}")
        if brand_meta.get("mp_sold"):
            meta_lines.append(f"Marketplace units sold: {brand_meta['mp_sold']:,}")
    meta_block = "\n".join(meta_lines)

    ad_blocks = []
    for i, ad in enumerate(sample_ads, 1):
        text = (ad.get("ad_text") or "")[:600]
        days = ad.get("days_running") or 0
        status = "active" if ad.get("is_active") else "stopped"
        ad_blocks.append(
            f"--- Ad {i} ({days}d, {status}) ---\n{text}"
        )
    ads_block = "\n\n".join(ad_blocks)

    user_msg = f"""Brand data:
{meta_block}

Sample ads (curated — longest-running + oldest):

{ads_block}

Write the analyst report now. Markdown formatting."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=900,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        report = resp.content[0].text.strip() if resp.content else ""
        return {
            "ok": True, "report_markdown": report,
            "error": None, "ads_used": len(sample_ads),
        }
    except Exception as e:
        return {
            "ok": False, "report_markdown": "",
            "error": f"{type(e).__name__}: {e}",
            "ads_used": 0,
        }
