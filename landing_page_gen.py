"""AI landing page copy generator for PH ecom products.

Produces full Taglish landing page sections:
  - Headline (problem)
  - Sub-headline (solution promise)
  - USP bullet points (3-5)
  - Social proof block (template testimonials)
  - How-to-use steps
  - FAQ (5 common PH buyer questions)
  - CTA section

Output as Markdown — user can copy into Wix / Shopify / Shopee description.

Cost: ~$0.01-0.03 per page. Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("pra.landing")


SYSTEM_PROMPT = """You are a senior conversion copywriter who has launched
dozens of PH ecommerce products. Write landing-page copy that sells without
sounding like spam.

Output a complete landing page in MARKDOWN with these sections in this order:

# [Compelling Headline — focus on the buyer's pain or desired outcome]

## [Sub-headline — promise the solution in one sentence]

### Why this works
- [USP 1: specific benefit, not generic]
- [USP 2: backed by evidence — ingredient, days, units sold]
- [USP 3: PH-relevant social proof]
- [USP 4: risk reversal — money back, COD, fast shipping]
- [USP 5: scarcity/urgency that's HONEST not fake]

### Real stories from Filipino customers
> "[Testimonial 1 — name + city + specific result]"
>
> "[Testimonial 2]"
>
> "[Testimonial 3]"

### How to use
1. [Step 1 — simple instruction]
2. [Step 2]
3. [Step 3]
4. [Step 4 — what to expect after X days]

### Frequently asked questions

**Q: [common PH-buyer question]**
A: [direct answer, Taglish OK]

**Q: [shipping/COD question]**
A: [answer]

**Q: [safety/side effects question]**
A: [answer — be honest, don't overpromise]

**Q: [comparison-to-competitors question]**
A: [answer]

**Q: [refund/guarantee question]**
A: [answer]

### Order now
[2-3 sentence closing CTA. Specify what happens next. Include payment +
shipping options: COD, GCash, Maya, Shopee/Lazada checkout.]

GUIDELINES:
- Voice: friend recommending, not corporate. Taglish unless user specified another language.
- NO illegal FDA claims (cure cancer, treat diabetes, etc.) — keep claims wellness-grade.
- Include realistic PH context: GCash, COD, J&T/LBC, ₱ pricing.
- Total ~600-900 words. Punchy paragraphs, generous whitespace.
- Bold the most important phrase in each section."""


def generate(product_name: str, niche: str = "", price_php: float = 0,
             pain_point: str = "", target_audience: str = "",
             ingredients: str = "", language: str = "Taglish",
             model: str = "claude-haiku-4-5",
             api_key: str | None = None) -> dict[str, Any]:
    """Generate a full landing page.

    Returns: {ok, markdown, error}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "markdown": "",
                "error": "ANTHROPIC_API_KEY env var not set."}
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "markdown": "",
                "error": "anthropic SDK not installed."}

    parts = [
        f"Product: {product_name}",
        f"Niche: {niche}" if niche else "",
        f"Price: ₱{price_php:,.0f}" if price_php else "",
        f"Pain point / problem: {pain_point}" if pain_point else "",
        f"Target audience: {target_audience}" if target_audience else "",
        f"Key ingredients / features: {ingredients}" if ingredients else "",
        f"Language: {language}",
        "",
        "Write the full landing page in Markdown now.",
    ]
    user_msg = "\n".join(p for p in parts if p)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        return {"ok": True, "markdown": text, "error": None}
    except Exception as e:
        return {"ok": False, "markdown": "",
                "error": f"{type(e).__name__}: {e}"}
