"""Telegram daily-summary notifications.

Setup (one-time, free):
  1. Open Telegram, search @BotFather, type /newbot, follow prompts. Save the token.
  2. Open a chat with your new bot and send any message (so it can reply to you).
  3. Visit https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates to find your chat_id
     (look for `"chat":{"id":12345,...}`).
  4. In the app's Notifications tab, paste the token + chat_id and save.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

import db

log = logging.getLogger("pra.notify")

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "notifications_config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("telegram_token") and cfg.get("telegram_chat_id"))


def send_telegram(text: str, parse_mode: str = "Markdown") -> tuple[bool, str]:
    cfg = load_config()
    token = cfg.get("telegram_token")
    chat_id = cfg.get("telegram_chat_id")
    if not (token and chat_id):
        return False, "Telegram not configured. Set token + chat_id in Notifications tab."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, data={
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }, timeout=15)
        if r.status_code == 200 and r.json().get("ok"):
            return True, "Sent."
        return False, f"Telegram API error: {r.status_code} {r.text[:200]}"
    except requests.RequestException as e:
        return False, f"Network error: {e}"


def _format_brand_line(brand: str, niche: str, days: int) -> str:
    return f"• *{brand}* — {niche}, {days} days"


def build_daily_summary() -> str:
    """Compose a Telegram-formatted summary of the latest scrape vs. previous."""
    db.init_db()
    runs = db.list_runs(limit=2, only_meta=True)
    if not runs:
        return "📭 No runs in DB yet — nothing to summarise."

    latest = runs[0]
    # A11: brands you've tagged as competitors are noise in a "new winners"
    # alert — keep a set to filter them out below.
    try:
        _competitors = {b.casefold() for b in db.list_competitor_brands()}
    except Exception:
        _competitors = set()
    all_latest = db.ads_for_run(latest["run_id"])
    n_total = len(all_latest)
    n_active = sum(1 for a in all_latest if a.get("is_active"))
    n_ph = sum(1 for a in all_latest if a.get("geo_signal") == "ph-confident")
    n_in_niche = sum(1 for a in all_latest if a.get("niche_relevance") == "match")
    n_enriched = sum(1 for a in all_latest if a.get("mp_enriched_at"))

    # The summary should surface PH-confident, in-niche winners by default.
    # Fall back to all ads if filters leave too few (e.g. early runs not yet annotated).
    latest_ads = [
        a for a in all_latest
        if a.get("geo_signal") in ("ph-confident", "ph-likely")
        and a.get("niche_relevance") != "no_match"
    ]
    if len(latest_ads) < 20:
        latest_ads = all_latest

    by_niche_active: dict[str, int] = defaultdict(int)
    by_niche_brands: dict[str, set] = defaultdict(set)
    for a in latest_ads:
        if a.get("is_active"):
            n = a.get("niche") or "?"
            by_niche_active[n] += 1
            b = a.get("brand") or a.get("page_name")
            if b:
                by_niche_brands[n].add(b)

    # Top sustained brands by score_normalized
    top_brands_agg: dict[str, dict] = {}
    for a in latest_ads:
        if not a.get("is_active"):
            continue
        if (a.get("days_running") or 0) < 90:
            continue
        b = a.get("brand") or a.get("page_name")
        if not b or b.casefold() in _competitors:
            continue
        entry = top_brands_agg.setdefault(b, {
            "brand": b, "niche": a.get("niche"),
            "max_days": 0, "ad_count": 0, "score": 0.0,
        })
        entry["max_days"] = max(entry["max_days"], a.get("days_running") or 0)
        entry["ad_count"] += 1
        entry["score"] += float(a.get("score_normalized") or 0)
    top3 = sorted(top_brands_agg.values(), key=lambda x: -x["score"])[:3]

    # New winners since prior run
    new_winners: list[dict] = []
    retired_brands: dict[str, int] = defaultdict(int)
    if len(runs) >= 2:
        prev = db.ads_for_run(runs[1]["run_id"])
        if len(prev) >= max(50, n_total // 2):  # comparable
            prev_ids = {a.get("library_id"): a for a in prev}
            curr_ids = {a.get("library_id") for a in latest_ads}
            seen_brand: set = set()
            for a in sorted(latest_ads, key=lambda x: -(x.get("days_running") or 0)):
                if not a.get("is_active") or (a.get("days_running") or 0) < 30:
                    continue
                pa = prev_ids.get(a.get("library_id"))
                if pa is None or (pa.get("days_running") or 0) >= 30:
                    continue
                b = a.get("brand") or a.get("page_name") or "?"
                if b in seen_brand or b.casefold() in _competitors:
                    continue
                seen_brand.add(b)
                new_winners.append(a)
                if len(new_winners) >= 5:
                    break
            for a in prev:
                if not a.get("is_active"):
                    continue
                if a.get("library_id") not in curr_ids:
                    b = a.get("brand") or a.get("page_name") or "?"
                    retired_brands[b] += 1

    # Build markdown message
    lines = [
        f"🛍️ *Orbit — Daily Summary*",
        f"_{datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        "",
        f"📊 *Run #{latest['run_id']}*: {n_total} ads, {n_active} active",
        f"PH-confident: {n_ph} · In-niche: {n_in_niche} · Marketplace-enriched: {n_enriched}",
        "",
    ]
    if new_winners:
        lines.append("🔥 *New 30-day winners*")
        for a in new_winners:
            lines.append(_format_brand_line(
                a.get("brand") or a.get("page_name") or "?",
                a.get("niche") or "?",
                a.get("days_running") or 0,
            ))
        lines.append("")
    if retired_brands:
        top_retired = sorted(retired_brands.items(), key=lambda x: -x[1])[:5]
        lines.append("💀 *Retirements (active → gone)*")
        for b, c in top_retired:
            lines.append(f"• {b} — {c} ad{'s' if c > 1 else ''} stopped")
        lines.append("")
    if by_niche_active:
        lines.append("📈 *Niche heat (active brands)*")
        for niche, brands in sorted(by_niche_brands.items(), key=lambda x: -len(x[1])):
            lines.append(f"• {niche}: {len(brands)} brands, {by_niche_active[niche]} active ads")
        lines.append("")
    # A7: saturation spikes — niches where unique competitors jumped run-on-run.
    try:
        _sat = db.niche_brand_delta()
        _spikes = sorted(
            [(n, d) for n, d in _sat.items()
             if d.get("pct", 0) >= 30 and d.get("curr", 0) >= 3],
            key=lambda x: -x[1]["pct"],
        )
    except Exception:
        _spikes = []
    if _spikes:
        lines.append("⚠️ *Saturation spikes (more competitors)*")
        for n, d in _spikes[:5]:
            lines.append(f"• {n}: {d['prev']}→{d['curr']} brands (+{d['pct']:.0f}%)")
        lines.append("")
    if top3:
        lines.append("🏆 *Top sustained winners*")
        for i, b in enumerate(top3, 1):
            lines.append(f"{i}. *{b['brand']}* — {b['niche']}, {b['max_days']} days, {b['ad_count']} ads")
        lines.append("")
    lines.append("Open dashboard → http://localhost:8501")
    return "\n".join(lines)


def send_daily_summary() -> tuple[bool, str]:
    if not is_configured():
        return False, "Telegram not configured."
    text = build_daily_summary()
    return send_telegram(text)
