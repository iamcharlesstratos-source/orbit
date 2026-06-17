"""Generate Midjourney / Stable Diffusion prompts from winning ads.

Takes a brand's hero ad text + visual brief and produces 6 image prompts
optimized for AI image generators (Midjourney, Stable Diffusion, DALL-E,
Flux). Each prompt covers a different creative angle.

Cost: ~$0.005 per generation. Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("pra.image_prompt")


SYSTEM_PROMPT = """You are an AI image-prompt engineer specializing in
Filipino e-commerce ad creatives. You write prompts that produce SCROLL-STOPPING
ad images for Filipino audiences.

Your prompts follow this proven structure:
  <subject> <action> <setting> <styling> <camera/composition> <lighting> <vibe>

Output EXACTLY 6 image prompts as a numbered markdown list. Each prompt:
- 30-60 words, dense with visual descriptors
- Specifies aspect ratio (1:1 for IG/FB feed, 9:16 for stories/reels)
- Filipino-cultural details where appropriate (model ethnicity, setting,
  context — "Filipina woman in her 30s in a Manila condo bathroom")
- Avoids text overlay requests (those are handled separately)
- Covers different angles: lifestyle, product hero, before/after, social proof,
  studio product, candid moment

NO preamble, no explanations. Just the 6 prompts."""


def generate(product_name: str, ad_copy: str = "", niche: str = "",
             target_audience: str = "",
             model: str = "claude-haiku-4-5",
             api_key: str | None = None) -> dict[str, Any]:
    """Generate 6 image prompts based on a product + winning ad context.

    Returns: {ok, prompts_markdown, error}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "prompts_markdown": "",
                "error": "ANTHROPIC_API_KEY env var not set."}
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "prompts_markdown": "",
                "error": "anthropic SDK not installed."}

    user_msg_parts = [
        f"Product: {product_name}",
        f"Niche: {niche}" if niche else "",
        f"Target audience: {target_audience}" if target_audience else "",
        "",
        "Sample winning ad copy (for context — match the vibe):",
        ad_copy[:600] if ad_copy else "(no copy provided)",
        "",
        "Write 6 image prompts now. Numbered list, markdown.",
    ]
    user_msg = "\n".join(p for p in user_msg_parts if p)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        return {"ok": True, "prompts_markdown": text, "error": None}
    except Exception as e:
        return {"ok": False, "prompts_markdown": "",
                "error": f"{type(e).__name__}: {e}"}
