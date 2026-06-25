"""LLM-powered ad classification via Claude API.

Tags each ad with:
  hook_angle:  scarcity | social-proof | before-after | problem-solution | claim | testimonial | demo | curiosity
  claim_type:  medical | lifestyle | testimonial | discount | result-promise | other
  target_demo: mom | gym | boomer | gen-z | working-pro | beauty | other

Cost: ~$0.005 per ad with claude-haiku. 1000 ads ≈ $5 one-time.
Needs ANTHROPIC_API_KEY in env.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

log = logging.getLogger("pra.llm")


SYSTEM_PROMPT = """You are an ad copy classifier for Philippine ecommerce. Read each ad text and return strict JSON with three fields:

- hook_angle: ONE of [scarcity, social-proof, before-after, problem-solution, claim, testimonial, demo, curiosity, other]
- claim_type: ONE of [medical, lifestyle, testimonial, discount, result-promise, other]
- target_demo: ONE of [mom, gym, boomer, gen-z, working-pro, beauty, men, women, other]

Return only valid JSON, no commentary."""


def _classify_one(client, text: str, model: str) -> dict | None:
    """Call Claude API on one ad text. Returns {hook_angle, claim_type, target_demo} or None."""
    if not text or len(text.strip()) < 10:
        return None
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=120,
            # A6: cache the system prompt — it's identical for every ad in the
            # batch, so calls after the first reuse it (savings scale with prompt
            # size; harmless if below the cache minimum).
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            # A5: prefill the assistant turn with "{" so Claude emits pure JSON —
            # no markdown fences to strip, no JSONDecodeError killing the batch.
            messages=[
                {"role": "user", "content": text[:1500]},
                {"role": "assistant", "content": "{"},
            ],
        )
        body = resp.content[0].text.strip() if resp.content else ""
        if not body.startswith("{"):
            body = "{" + body  # restore the prefilled brace
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # last-resort: strip code fences if the model still wrapped it
            b = body.strip().strip("`").strip()
            if b.startswith("json"):
                b = b[4:].strip()
            return json.loads(b)
    except Exception as e:
        log.debug("LLM classify failed: %s", e)
        return None


def classify_run(run_id: int, max_ads: int = 200,
                  model: str = "claude-haiku-4-5",
                  api_key: str | None = None) -> tuple[int, int]:
    """Classify unclassified ads in a run via Claude API.
    Returns (attempted, succeeded)."""
    import db
    try:
        import anthropic
    except ImportError:
        log.error("anthropic SDK not installed — run: pip install anthropic")
        return (0, 0)

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY env var not set")
        return (0, 0)

    client = anthropic.Anthropic(api_key=api_key)

    # Find ads needing classification — has ad_text, no llm_classified_at
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT library_id, ad_text, score_normalized FROM ads
               WHERE run_id = ?
                 AND ad_text IS NOT NULL AND ad_text <> ''
                 AND (llm_classified_at IS NULL OR llm_classified_at = '')
               ORDER BY score_normalized DESC
               LIMIT ?""",
            (run_id, max_ads),
        ).fetchall()
        pending = [dict(r) for r in rows]

    if not pending:
        log.info("No ads need classification in run %d", run_id)
        return (0, 0)

    log.info("LLM classifying %d ads (model=%s)...", len(pending), model)
    succeeded = 0
    now = datetime.now().isoformat(timespec="seconds")

    for i, ad in enumerate(pending):
        result = _classify_one(client, ad["ad_text"], model)
        if result:
            try:
                with db.connect() as conn:
                    conn.execute(
                        """UPDATE ads SET llm_hook_angle = ?, llm_claim_type = ?,
                           llm_target_demo = ?, llm_classified_at = ?
                           WHERE library_id = ? AND run_id = ?""",
                        (
                            result.get("hook_angle", ""),
                            result.get("claim_type", ""),
                            result.get("target_demo", ""),
                            now,
                            ad["library_id"],
                            run_id,
                        ),
                    )
                succeeded += 1
            except Exception as e:
                log.debug("DB write failed for %s: %s", ad["library_id"], e)
        if (i + 1) % 25 == 0:
            log.info("  ... %d/%d classified, %d successful", i + 1, len(pending), succeeded)

    log.info("LLM classification done: %d/%d succeeded", succeeded, len(pending))
    return (len(pending), succeeded)
