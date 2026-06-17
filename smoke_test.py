"""Smoke test — runs scraper against one keyword with tight limits to verify wiring."""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scraper import run
from scorer import rank_ads


config = {
    "country": "PH",
    "active_status": "active",
    "max_ads_per_keyword": 15,
    "scroll_pause_ms": 2500,
    "max_scroll_rounds": 4,
    "headless": True,
    "niches": {
        "capsule": ["slimming capsule"],
    },
}

results = run(config, ["capsule"])
rows = [a.to_row() for a in results["capsule"]]
ranked = rank_ads(rows)

print(f"\n=== SMOKE TEST RESULTS ===")
print(f"Total ads parsed: {len(ranked)}")
if ranked:
    sample = ranked[0]
    print("\nTop ad (sample fields):")
    for k in ("page_name", "library_id", "start_date", "days_running", "is_active", "platforms", "score"):
        print(f"  {k}: {sample.get(k)!r}")
    print(f"  ad_text (first 200 chars): {sample.get('ad_text', '')[:200]!r}")
    print(f"  landing_url: {sample.get('landing_url', '')[:120]!r}")
else:
    print("WARNING: 0 ads parsed — selectors may be stale OR no active ads matched.")
