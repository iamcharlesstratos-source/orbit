"""Google Trends overlay — search interest for a brand/keyword in the PH market."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("pra.trends")


def fetch_trend(query: str, months: int = 12, geo: str = "PH") -> dict:
    """Returns {labels: [date strings], values: [int 0-100], avg: float, error: str|None}.
    Uses pytrends — graceful degrade on rate limits / network errors."""
    out = {"labels": [], "values": [], "avg": 0.0, "error": None}
    try:
        from pytrends.request import TrendReq
    except ImportError:
        out["error"] = "pytrends not installed"
        return out

    try:
        py = TrendReq(hl="en-US", tz=480, timeout=(10, 25),
                      retries=2, backoff_factor=0.4)
        timeframe = f"today {months}-m"
        py.build_payload([query], cat=0, timeframe=timeframe, geo=geo, gprop="")
        df = py.interest_over_time()
        if df is None or df.empty:
            out["error"] = "no data for this query in PH"
            return out
        col = df[query] if query in df.columns else df.iloc[:, 0]
        out["labels"] = [ts.strftime("%Y-%m") for ts in df.index]
        out["values"] = [int(v) for v in col.tolist()]
        if out["values"]:
            out["avg"] = round(sum(out["values"]) / len(out["values"]), 1)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log.debug("Trends fetch failed for %r: %s", query, e)
    return out


def fetch_multi(queries: list[str], months: int = 12, geo: str = "PH") -> dict:
    """Compare PH search interest for up to 5 queries in a SINGLE Google Trends
    request (Google normalizes them against each other, so values are directly
    comparable). One request = low rate-limit risk. Returns
    {labels: [...], series: {query: [int 0-100]}, error: str|None}."""
    out: dict = {"labels": [], "series": {}, "error": None}
    queries = [q.strip() for q in (queries or []) if q and q.strip()][:5]
    if not queries:
        out["error"] = "no queries"
        return out
    try:
        from pytrends.request import TrendReq
    except ImportError:
        out["error"] = "pytrends not installed"
        return out
    try:
        py = TrendReq(hl="en-US", tz=480, timeout=(10, 25),
                      retries=2, backoff_factor=0.4)
        py.build_payload(queries, cat=0, timeframe=f"today {months}-m", geo=geo, gprop="")
        df = py.interest_over_time()
        if df is None or df.empty:
            out["error"] = "no data for these queries in PH"
            return out
        out["labels"] = [ts.strftime("%Y-%m") for ts in df.index]
        for q in queries:
            if q in df.columns:
                out["series"][q] = [int(v) for v in df[q].tolist()]
        if not out["series"]:
            out["error"] = "no comparable data returned"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        log.debug("Trends multi fetch failed for %r: %s", queries, e)
    return out


def trend_summary(trend: dict) -> str:
    """Short description: rising / falling / stable."""
    vals = trend.get("values") or []
    if len(vals) < 4:
        return "insufficient data"
    recent = sum(vals[-3:]) / 3
    earlier = sum(vals[:3]) / 3
    if earlier == 0:
        return "rising (no early signal)"
    delta_pct = (recent - earlier) / max(earlier, 1) * 100
    if delta_pct > 30:
        return f"rising +{delta_pct:.0f}% vs start"
    if delta_pct < -30:
        return f"falling {delta_pct:.0f}% vs start"
    return f"stable ({delta_pct:+.0f}% vs start)"
