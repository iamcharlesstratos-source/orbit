"""AI Ad Copy Generator — Taglish ad variations using proven hook phrases from your DB.

Uses Claude API + grounds the generation in your tracked winning hook patterns.
Cost: ~$0.005 per generation (claude-haiku).
Needs ANTHROPIC_API_KEY env var.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("pra.adcopy")


# Language modes — each gets a tailored prompt voice
_LANG_INSTRUCTIONS = {
    "Taglish": (
        "Mix English and Tagalog naturally like Filipino sellers do. "
        "Use Tagalog filler words ('po', 'nga', 'kasi', 'naman'). "
        "Sound like a Pinoy/Pinay friend recommending the product."
    ),
    "Tagalog": (
        "Pure Tagalog/Filipino, conversational tone. "
        "No English except product names. Sound like a barangay tita recommending."
    ),
    "English": (
        "Filipino English (slight Pinoy flavor). "
        "Conversational, friendly, not corporate."
    ),
    # Phase 16.8 — PH regional languages for niche-targeted ads
    "Bisaya (Cebuano)": (
        "Pure Bisaya / Cebuano. Use natural Visayan filler words ('bay', 'oy', "
        "'dah', 'ba', 'jud', 'lagi'). Sound like a Cebuano kabay friend recommending. "
        "Target audience: Cebu, Davao, Visayas, Mindanao buyers. "
        "Use 'kumusta' instead of 'kamusta', 'palihug' instead of 'paki', "
        "'maayong adlaw' for greetings. No English/Tagalog except product names."
    ),
    "Bisalish (Bisaya-English mix)": (
        "Mix English and Bisaya/Cebuano naturally like Visayan sellers do online. "
        "Use Bisaya filler words ('bay', 'jud', 'oy', 'dah'). "
        "Sound like a Cebu-based seller friend recommending. Targets Visayas + Mindanao."
    ),
    "Ilocano": (
        "Pure Ilocano. Use natural Ilocano filler words ('apo', 'ngamin', 'gayam', "
        "'kunak', 'manong/manang'). Target audience: Ilocos region, Pangasinan, "
        "La Union, Northern Luzon buyers. Use 'kumusta' or 'naimbag a aldaw' for "
        "greetings. No English/Tagalog except product names."
    ),
    "Ilocanglish (Ilocano-English mix)": (
        "Mix English and Ilocano naturally like Northern Luzon sellers do. "
        "Use Ilocano filler words ('apo', 'gayam', 'ngata'). "
        "Sound like an Ilocano friend recommending. Targets Northern Luzon."
    ),
    "Hiligaynon (Ilonggo)": (
        "Pure Hiligaynon / Ilonggo. Use natural Ilonggo filler words ('ba', 'gid', "
        "'haw', 'lang', 'man'). Target audience: Iloilo, Bacolod, Western Visayas. "
        "Sound soft-spoken and friendly — Ilonggo melodic tone. "
        "No English/Tagalog except product names."
    ),
}

# Hook angle templates — gives variation in approach
_HOOK_ANGLES = [
    "Problem-solution: lead with a problem the customer has, then product as solution.",
    "Before-after transformation story.",
    "Social proof: real customer story / multiple users / 'mga madam, mga ate' tone.",
    "Scarcity/urgency: limited stock, today only, ending soon.",
    "Curiosity: question or surprising claim that makes reader want to learn more.",
    "Benefit-driven: lead with the strongest physical or emotional benefit.",
]


SYSTEM_PROMPT_TEMPLATE = """You are an expert Filipino ecommerce ad copywriter who has written thousands of high-converting ads for Philippine sellers on Facebook, Shopee, Lazada, and TikTok Shop.

You write ads that sound like a Filipino friend recommending — not corporate, not salesy. You know which phrases convert because you study what's already winning in the PH market.

LANGUAGE: {language_instruction}

PROVEN WINNING HOOK PHRASES (used by ads that have run 30+ days successfully in PH):
{hook_phrases}

You will write ad copy that NATURALLY weaves these proven phrases into your output. Don't force them — use them when they fit naturally. Mix in fresh phrases too.

OUTPUT FORMAT: Return EXACTLY 6 ad variations as a numbered list. Each variation:
- 2–4 sentences
- Starts with a hook (question, claim, problem, surprise, etc.)
- Ends with a soft CTA (e.g., "PM us", "Order now", "Limited stock", "Try mo na")
- Different angle per variation (vary hook style)

Do NOT include preamble or explanations. Just the 6 numbered ads."""


def _get_hook_phrases(niche: str, top_n: int = 25) -> list[str]:
    """Pull winning hook phrases from existing DB via hook_analyzer."""
    try:
        import db
        import hook_analyzer
        rows = db.ads_for_run(db.latest_run_id(only_meta=True))
        phrases = hook_analyzer.extract_phrases(
            rows,
            n_range=(2, 4),
            top_n=top_n,
            min_count=2,
            niche=niche if niche != "all" else None,
        )
        return [p["phrase"] for p in phrases]
    except Exception as e:
        log.debug("hook fetch failed: %s", e)
        return []


def generate(
    product_name: str,
    niche: str = "all",
    language: str = "Taglish",
    audience_note: str = "",
    model: str = "claude-haiku-4-5",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate 6 ad copy variations.

    Returns: {ok: bool, text: str, error: str | None, hooks_used: list[str]}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "text": "",
            "error": "ANTHROPIC_API_KEY env var not set. Set your Claude API key first.",
            "hooks_used": [],
        }

    try:
        import anthropic
    except ImportError:
        return {
            "ok": False,
            "text": "",
            "error": "anthropic SDK not installed — run: pip install anthropic",
            "hooks_used": [],
        }

    hooks = _get_hook_phrases(niche, top_n=25)
    hook_block = (
        "\n".join(f"- {h}" for h in hooks) if hooks
        else "(no DB hooks yet — write fresh PH copy)"
    )
    lang_instr = _LANG_INSTRUCTIONS.get(language, _LANG_INSTRUCTIONS["Taglish"])

    system = SYSTEM_PROMPT_TEMPLATE.format(
        language_instruction=lang_instr,
        hook_phrases=hook_block,
    )

    user_msg_parts = [
        f"Product: {product_name}",
        f"Niche: {niche}" if niche and niche != "all" else "",
        f"Target audience: {audience_note}" if audience_note else "",
        "",
        "Write 6 ad variations now, each with a different hook angle.",
    ]
    user_msg = "\n".join(p for p in user_msg_parts if p)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text if resp.content else ""
        return {
            "ok": True,
            "text": text.strip(),
            "error": None,
            "hooks_used": hooks[:10],
        }
    except Exception as e:
        return {
            "ok": False,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
            "hooks_used": hooks[:5],
        }
