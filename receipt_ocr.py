"""BIR / Official Receipt OCR via Claude Vision.

Upload a photo of a PH sales receipt (BIR OR, Shopee invoice, Lazada slip,
courier-side proof of delivery, supplier invoice, etc.) and extract:
  - date
  - line items (qty, description, unit price)
  - subtotal / VAT / total
  - merchant name / TIN

Returns structured JSON. Caller decides which fields to push into ROI.

Cost: ~$0.005-0.02 per receipt at claude-haiku rates.
Needs ANTHROPIC_API_KEY env var.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("pra.ocr")


SYSTEM_PROMPT = """You are an OCR + extraction engine for Philippine sales receipts.
Read the receipt image and return STRICT JSON only (no markdown, no commentary).

Expected JSON shape:
{
  "date": "YYYY-MM-DD or null",
  "merchant_name": "string or null",
  "merchant_tin": "TIN if visible, or null",
  "receipt_type": "BIR_OR | Shopee | Lazada | TikTok_Shop | other | unknown",
  "line_items": [
    {"qty": int, "description": "string", "unit_price_php": float, "subtotal_php": float}
  ],
  "subtotal_php": float or null,
  "vat_php": float or null,
  "total_php": float or null,
  "or_number": "string or null",
  "currency": "PHP",
  "confidence": "high | medium | low",
  "notes": "any caveats — illegible parts, partial matches"
}

If the image isn't a receipt, return:
  {"error": "not_a_receipt", "notes": "<what was visible>"}
"""


def extract_from_image(image_bytes: bytes, mime_type: str = "image/jpeg",
                       model: str = "claude-haiku-4-5",
                       api_key: str | None = None) -> dict[str, Any]:
    """Run Claude Vision OCR on a single receipt image.

    Args:
        image_bytes: raw bytes of the image file
        mime_type: e.g. 'image/jpeg', 'image/png', 'image/webp'
        model: Claude model (haiku recommended for cost)
        api_key: override env var

    Returns:
        {ok, data, error, raw_response}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "ok": False, "data": None,
            "error": "ANTHROPIC_API_KEY env var not set.",
            "raw_response": "",
        }
    try:
        import anthropic
    except ImportError:
        return {
            "ok": False, "data": None,
            "error": "anthropic SDK not installed (pip install anthropic).",
            "raw_response": "",
        }
    if not image_bytes:
        return {"ok": False, "data": None, "error": "empty image", "raw_response": ""}
    if len(image_bytes) > 10 * 1024 * 1024:  # 10 MB
        return {
            "ok": False, "data": None,
            "error": "Image too large (>10MB). Compress or crop first.",
            "raw_response": "",
        }

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": ("Extract the receipt data. Return only JSON. "
                                 "Use null for missing fields."),
                    },
                ],
            }],
        )
        raw = resp.content[0].text.strip() if resp.content else ""
        # Strip any code fences
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as je:
            return {
                "ok": False, "data": None,
                "error": f"Could not parse JSON response: {je}",
                "raw_response": raw[:500],
            }
        return {"ok": True, "data": data, "error": None, "raw_response": raw}
    except Exception as e:
        return {
            "ok": False, "data": None,
            "error": f"{type(e).__name__}: {e}",
            "raw_response": "",
        }
