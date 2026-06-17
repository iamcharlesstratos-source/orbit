"""SQLite persistence layer for Product Research Agent.

Stores every scrape as a `run`, every ad observation linked to a run.
A given library_id can appear in many runs — that's how we know an ad
has been continuously active for N scrapes (true longevity signal).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("pra.db")

ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "db"
DB_PATH = DB_DIR / "agent.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    niches TEXT,
    total_ads INTEGER DEFAULT 0,
    source TEXT DEFAULT 'scrape',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS ads (
    library_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    keyword TEXT,
    niche TEXT,
    page_name TEXT,
    brand TEXT,
    start_date TEXT,
    end_date TEXT,
    is_active INTEGER,
    days_running INTEGER,
    platforms TEXT,
    ad_text TEXT,
    landing_url TEXT,
    media_type TEXT,
    media_url TEXT,
    score REAL,
    variants_from_brand INTEGER,
    scraped_at TEXT,
    PRIMARY KEY (library_id, run_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ads_library_id ON ads(library_id);
CREATE INDEX IF NOT EXISTS idx_ads_brand ON ads(brand);
CREATE INDEX IF NOT EXISTS idx_ads_niche ON ads(niche);
CREATE INDEX IF NOT EXISTS idx_ads_run_id ON ads(run_id);
CREATE INDEX IF NOT EXISTS idx_ads_is_active ON ads(is_active);

CREATE TABLE IF NOT EXISTS creatives (
    library_id TEXT PRIMARY KEY,
    media_type TEXT,
    media_path TEXT,
    media_url TEXT,
    downloaded_at TEXT,
    file_size INTEGER
);

CREATE TABLE IF NOT EXISTS product_testing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_added TEXT NOT NULL,
    product_name TEXT NOT NULL,
    brand_name TEXT,
    niche TEXT,
    hunted_by TEXT,
    pain_point TEXT,
    emotional_benefits TEXT,
    physical_effects TEXT,
    main_ingredients TEXT,
    target_age TEXT,
    target_gender TEXT,
    target_behavior TEXT,
    target_interest TEXT,
    target_demographics TEXT,
    status TEXT DEFAULT 'queued',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_testing_status ON product_testing(status);
CREATE INDEX IF NOT EXISTS idx_testing_date ON product_testing(date_added DESC);

CREATE TABLE IF NOT EXISTS brand_meta (
    brand TEXT PRIMARY KEY,
    starred INTEGER DEFAULT 0,
    status TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_brand_meta_starred ON brand_meta(starred);
CREATE INDEX IF NOT EXISTS idx_brand_meta_status ON brand_meta(status);

CREATE TABLE IF NOT EXISTS tiktok_ads (
    ad_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    captured_at TEXT,
    country TEXT,
    industry TEXT,
    advertiser TEXT,
    title TEXT,
    description TEXT,
    cta TEXT,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    plays INTEGER,
    ctr REAL,
    duration_seconds INTEGER,
    first_shown TEXT,
    last_shown TEXT,
    thumbnail_url TEXT,
    video_url TEXT,
    detail_url TEXT,
    raw_text TEXT,
    PRIMARY KEY (ad_id, run_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tiktok_likes ON tiktok_ads(likes);
CREATE INDEX IF NOT EXISTS idx_tiktok_run ON tiktok_ads(run_id);
"""


@contextmanager
def connect():
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_NEW_AD_COLUMNS: dict[str, str] = {
    "mp_source": "TEXT",
    "mp_currency": "TEXT",
    "mp_price": "REAL",
    "mp_sold": "INTEGER",
    "mp_rating": "REAL",
    "mp_reviews": "INTEGER",
    "mp_enriched_at": "TEXT",
    "geo_signal": "TEXT",
    "niche_relevance": "TEXT",
    "score_normalized": "REAL",
    "llm_hook_angle": "TEXT",
    "llm_claim_type": "TEXT",
    "llm_target_demo": "TEXT",
    "llm_classified_at": "TEXT",
    # Phase 14: category + sub_category + location
    "category":     "TEXT",
    "sub_category": "TEXT",
    "location":     "TEXT",
}


def _migrate(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(ads)").fetchall()}
    for name, ddl in _NEW_AD_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE ads ADD COLUMN {name} {ddl}")
    # brand_meta: competitor flag (Phase 20.2)
    bm_cols = {r["name"] for r in conn.execute("PRAGMA table_info(brand_meta)").fetchall()}
    if bm_cols and "competitor" not in bm_cols:
        conn.execute("ALTER TABLE brand_meta ADD COLUMN competitor INTEGER DEFAULT 0")
    # product_testing migration
    test_cols = {r["name"] for r in conn.execute("PRAGMA table_info(product_testing)").fetchall()}
    if test_cols and "hunted_by" not in test_cols:
        conn.execute("ALTER TABLE product_testing ADD COLUMN hunted_by TEXT")
    # ROI tracking columns (Phase 9.2)
    _NEW_TESTING_COLUMNS = {
        "launch_date":      "TEXT",      # when the product actually went live
        "units_sold":       "INTEGER",   # actual units sold
        "revenue_php":      "REAL",      # gross revenue PHP
        "ad_spend_php":     "REAL",      # FB/TikTok ad spend
        "cogs_php":         "REAL",      # cost of goods (per unit × units sold)
        "roas":             "REAL",      # revenue / ad_spend
        "net_profit_php":   "REAL",      # revenue - ad_spend - cogs
        "outcome":          "TEXT",      # winner / breakeven / loser / paused
        "learnings":        "TEXT",      # postmortem notes
    }
    if test_cols:
        for name, ddl in _NEW_TESTING_COLUMNS.items():
            if name not in test_cols:
                conn.execute(f"ALTER TABLE product_testing ADD COLUMN {name} {ddl}")
        # Launch checklist storage (Phase 10.4) — JSON-encoded checklist state per product
        if "launch_checklist" not in test_cols:
            conn.execute("ALTER TABLE product_testing ADD COLUMN launch_checklist TEXT")
        # PH DTI / FDA permit tracker (Phase 16.2)
        _PERMIT_COLUMNS = {
            "dti_permit_no":   "TEXT",
            "dti_expiry":      "TEXT",
            "fda_cpr_no":      "TEXT",
            "fda_expiry":      "TEXT",
            "bir_or_no":       "TEXT",  # BIR official receipt for paper trail
        }
        for name, ddl in _PERMIT_COLUMNS.items():
            if name not in test_cols:
                conn.execute(f"ALTER TABLE product_testing ADD COLUMN {name} {ddl}")


SEED_PATH = DB_DIR / "seed.sql"


def _maybe_restore_from_seed() -> None:
    """Cloud-friendly bootstrap: if the DB has no ads but a seed.sql exists,
    rebuild the database from the committed text seed.

    This makes deployment bulletproof — instead of uploading a fragile binary
    .db file to GitHub (which can get mangled / branch-mismatched), we ship a
    plain-text SQL dump that GitHub handles perfectly. On first cloud boot the
    app restores from it automatically.
    """
    try:
        if not SEED_PATH.exists():
            return
        DB_DIR.mkdir(exist_ok=True)

        # Decide whether to restore: only when the DB has NO ad rows.
        needs_restore = True
        if DB_PATH.exists():
            try:
                probe = sqlite3.connect(DB_PATH)
                n = probe.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
                probe.close()
                if n and n > 0:
                    needs_restore = False  # already populated — don't clobber
            except Exception:
                # ads table doesn't exist yet → the DB is fresh/empty → restore
                needs_restore = True

        if not needs_restore:
            return

        # IMPORTANT: the seed dump contains `CREATE TABLE` (not IF NOT EXISTS).
        # If an empty DB with tables already exists from a prior boot, those
        # CREATE statements collide and the whole restore fails. So delete the
        # existing (empty) DB file first and rebuild cleanly from the seed.
        if DB_PATH.exists():
            try:
                DB_PATH.unlink()
            except Exception:
                # Couldn't delete — fall back to a DROP-then-restore approach
                try:
                    _conn = sqlite3.connect(DB_PATH)
                    for tbl in ("ads", "runs", "brand_meta", "product_testing",
                                "tiktok_ads", "creatives", "seller_stores",
                                "seller_snapshots", "bestsellers"):
                        _conn.execute(f"DROP TABLE IF EXISTS {tbl}")
                    _conn.commit()
                    _conn.close()
                except Exception:
                    pass

        sql = SEED_PATH.read_text(encoding="utf-8")
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executescript(sql)
            conn.commit()
            log.info("Restored database from seed.sql")
        finally:
            conn.close()
    except Exception as e:
        log.warning("Seed restore skipped: %s", e)


def init_db() -> None:
    DB_DIR.mkdir(exist_ok=True)
    # Restore from seed BEFORE schema/migrations so cloud deploys get data
    _maybe_restore_from_seed()
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def start_run(niches: list[str], source: str = "scrape", notes: str = "") -> int:
    init_db()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, niches, source, notes) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), ",".join(niches), source, notes),
        )
        return cur.lastrowid


def finish_run(run_id: int, total_ads: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, total_ads = ? WHERE run_id = ?",
            (datetime.now().isoformat(timespec="seconds"), total_ads, run_id),
        )


def insert_ads(run_id: int, ads: Iterable[dict]) -> int:
    init_db()  # ensure migrations applied
    rows = []
    for a in ads:
        rows.append((
            a.get("library_id", ""),
            run_id,
            a.get("keyword", ""),
            a.get("niche", ""),
            a.get("page_name", ""),
            a.get("brand", "") or a.get("page_name", ""),
            a.get("start_date", ""),
            a.get("end_date", ""),
            1 if a.get("is_active") else 0,
            int(a.get("days_running") or 0),
            a.get("platforms", ""),
            a.get("ad_text", ""),
            a.get("landing_url", ""),
            a.get("media_type", ""),
            a.get("media_url", ""),
            float(a.get("score") or 0),
            int(a.get("variants_from_brand") or 0),
            a.get("scraped_at", ""),
            float(a.get("score_normalized") or 0),
            a.get("geo_signal", ""),
            a.get("niche_relevance", ""),
            a.get("category"),       # Phase 14
            a.get("sub_category"),   # Phase 14
            a.get("location"),       # Phase 14
        ))
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO ads
               (library_id, run_id, keyword, niche, page_name, brand, start_date, end_date,
                is_active, days_running, platforms, ad_text, landing_url, media_type, media_url,
                score, variants_from_brand, scraped_at,
                score_normalized, geo_signal, niche_relevance,
                category, sub_category, location)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def upsert_creative(library_id: str, media_type: str, media_path: str, media_url: str, file_size: int = 0) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO creatives
               (library_id, media_type, media_path, media_url, downloaded_at, file_size)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (library_id, media_type, media_path, media_url,
             datetime.now().isoformat(timespec="seconds"), file_size),
        )


def has_creative(library_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM creatives WHERE library_id = ? LIMIT 1", (library_id,)
        ).fetchone()
        return row is not None


def update_ad_enrichment(library_id: str, run_id: int, fields: dict) -> None:
    if not fields:
        return
    keys = [k for k in fields.keys() if k in _NEW_AD_COLUMNS or k in {
        "mp_source", "mp_currency", "mp_price", "mp_sold", "mp_rating",
        "mp_reviews", "mp_enriched_at", "geo_signal", "niche_relevance", "score_normalized",
    }]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = ?" for k in keys)
    values = [fields[k] for k in keys] + [library_id, run_id]
    with connect() as conn:
        conn.execute(
            f"UPDATE ads SET {set_clause} WHERE library_id = ? AND run_id = ?", values
        )


def update_ad_flags_bulk(run_id: int, library_id_to_fields: dict[str, dict]) -> int:
    """Bulk-update geo_signal/niche_relevance/score_normalized for a whole run."""
    if not library_id_to_fields:
        return 0
    with connect() as conn:
        n = 0
        for lib_id, fields in library_id_to_fields.items():
            if not fields:
                continue
            keys = list(fields.keys())
            set_clause = ", ".join(f"{k} = ?" for k in keys)
            conn.execute(
                f"UPDATE ads SET {set_clause} WHERE library_id = ? AND run_id = ?",
                [fields[k] for k in keys] + [lib_id, run_id],
            )
            n += 1
        return n


def ads_needing_enrichment(run_id: int) -> list[dict]:
    """Ads in this run that have a marketplace landing URL but aren't enriched yet."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT * FROM ads
               WHERE run_id = ?
                 AND landing_url <> ''
                 AND (mp_enriched_at IS NULL OR mp_enriched_at = '')
                 AND (
                       landing_url LIKE '%shopee.%' OR landing_url LIKE '%shp.ee%'
                    OR landing_url LIKE '%lazada.%'
                 )""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_runs(limit: int = 50, only_meta: bool = False) -> list[dict]:
    """List runs. If only_meta=True, exclude tiktok-source runs (which write to tiktok_ads,
    not ads). The main dashboard uses only_meta=True so TikTok runs don't confuse the
    Run selector."""
    with connect() as conn:
        if only_meta:
            rows = conn.execute(
                """SELECT r.*, COUNT(a.library_id) AS ads_count
                   FROM runs r LEFT JOIN ads a ON a.run_id = r.run_id
                   WHERE COALESCE(r.source,'') <> 'tiktok'
                   GROUP BY r.run_id
                   HAVING ads_count > 0
                   ORDER BY r.run_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


VALID_STATUSES = ("", "investigating", "validating", "launching", "passed", "launched")

# ---------- Product Testing CRUD ----------

TESTING_STATUSES = ("queued", "testing", "passed", "failed", "launched")


def insert_testing_product(data: dict) -> int:
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO product_testing
               (date_added, product_name, brand_name, niche, hunted_by,
                pain_point, emotional_benefits,
                physical_effects, main_ingredients, target_age, target_gender, target_behavior,
                target_interest, target_demographics, status, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("date_added") or now[:10],
                data.get("product_name", ""),
                data.get("brand_name", ""),
                data.get("niche", ""),
                data.get("hunted_by", ""),
                data.get("pain_point", ""),
                data.get("emotional_benefits", ""),
                data.get("physical_effects", ""),
                data.get("main_ingredients", ""),
                data.get("target_age", ""),
                data.get("target_gender", ""),
                data.get("target_behavior", ""),
                data.get("target_interest", ""),
                data.get("target_demographics", ""),
                data.get("status", "queued"),
                data.get("notes", ""),
                now,
                now,
            ),
        )
        return cur.lastrowid


def update_testing_product(product_id: int, data: dict) -> None:
    if not data:
        return
    now = datetime.now().isoformat(timespec="seconds")
    allowed = {
        # Basics
        "date_added", "product_name", "brand_name", "niche", "hunted_by",
        "pain_point", "emotional_benefits", "physical_effects", "main_ingredients",
        "target_age", "target_gender", "target_behavior", "target_interest",
        "target_demographics", "status", "notes",
        # ROI tracker (Phase 9.2)
        "launch_date", "units_sold", "revenue_php", "ad_spend_php",
        "cogs_php", "roas", "net_profit_php", "outcome", "learnings",
        # Launch checklist (Phase 10.4)
        "launch_checklist",
        # PH permits (Phase 16.2)
        "dti_permit_no", "dti_expiry", "fda_cpr_no", "fda_expiry", "bir_or_no",
    }
    updates = [(k, v) for k, v in data.items() if k in allowed]
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k, _ in updates) + ", updated_at = ?"
    values = [v for _, v in updates] + [now, product_id]
    with connect() as conn:
        conn.execute(f"UPDATE product_testing SET {set_clause} WHERE id = ?", values)


def delete_testing_product(product_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM product_testing WHERE id = ?", (product_id,))


def list_testing_products(status_filter: str = "") -> list[dict]:
    with connect() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM product_testing WHERE status = ? ORDER BY date_added DESC, id DESC",
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM product_testing ORDER BY date_added DESC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_testing_product(product_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM product_testing WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None


def get_brand_meta(brand: str) -> dict | None:
    if not brand:
        return None
    with connect() as conn:
        row = conn.execute("SELECT * FROM brand_meta WHERE brand = ?", (brand,)).fetchone()
        return dict(row) if row else None


def all_brand_meta() -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM brand_meta").fetchall()
        return {r["brand"]: dict(r) for r in rows}


def list_starred_brands() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT brand FROM brand_meta WHERE starred = 1 ORDER BY updated_at DESC"
        ).fetchall()
        return [r["brand"] for r in rows]


def upsert_brand_meta(brand: str, **fields) -> None:
    if not brand:
        return
    now = datetime.now().isoformat(timespec="seconds")
    init_db()
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM brand_meta WHERE brand = ?", (brand,)).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO brand_meta (brand, starred, status, notes, competitor, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    brand,
                    int(fields.get("starred", 0)),
                    fields.get("status", ""),
                    fields.get("notes", ""),
                    int(fields.get("competitor", 0)),
                    now,
                    now,
                ),
            )
        else:
            updates = []
            values: list = []
            for k in ("starred", "status", "notes", "competitor"):
                if k in fields:
                    updates.append(f"{k} = ?")
                    values.append(int(fields[k]) if k in ("starred", "competitor") else fields[k])
            if updates:
                updates.append("updated_at = ?")
                values.append(now)
                values.append(brand)
                conn.execute(f"UPDATE brand_meta SET {', '.join(updates)} WHERE brand = ?", values)


def toggle_star(brand: str) -> bool:
    """Flip the starred flag. Returns the new value."""
    current = get_brand_meta(brand) or {}
    new_starred = 0 if current.get("starred") else 1
    upsert_brand_meta(brand, starred=new_starred)
    return bool(new_starred)


def toggle_competitor(brand: str) -> bool:
    """Flip the competitor flag (Phase 20.2). Returns the new value."""
    current = get_brand_meta(brand) or {}
    new_val = 0 if current.get("competitor") else 1
    upsert_brand_meta(brand, competitor=new_val)
    return bool(new_val)


def list_competitor_brands() -> list[str]:
    init_db()
    with connect() as conn:
        try:
            rows = conn.execute(
                "SELECT brand FROM brand_meta WHERE competitor = 1 ORDER BY brand"
            ).fetchall()
        except Exception:
            return []
    return [r["brand"] for r in rows]


def cleanup_empty_runs(min_age_minutes: int = 30) -> int:
    """Delete runs older than min_age_minutes that have no rows in `ads` or `tiktok_ads`.
    Keeps recent runs (might still be in progress) and any run with at least one ad."""
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.now() - _td(minutes=min_age_minutes)).isoformat(timespec="seconds")
    with connect() as conn:
        return conn.execute(
            """DELETE FROM runs
               WHERE run_id NOT IN (SELECT DISTINCT run_id FROM ads)
                 AND run_id NOT IN (SELECT DISTINCT run_id FROM tiktok_ads)
                 AND started_at < ?""",
            (cutoff,),
        ).rowcount


# ============================================================
# Phase 20.1 — Creative swipe file (save winning creatives into collections)
# ============================================================

_SWIPE_SCHEMA = """
CREATE TABLE IF NOT EXISTS swipe_collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS swipe_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL,
    brand TEXT,
    niche TEXT,
    creative_path TEXT,
    landing_url TEXT,
    ad_text TEXT,
    notes TEXT,
    saved_at TEXT NOT NULL,
    FOREIGN KEY(collection_id) REFERENCES swipe_collections(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_swipe_item_coll ON swipe_items(collection_id);
"""


def _ensure_swipe_tables(conn) -> None:
    conn.executescript(_SWIPE_SCHEMA)


def list_swipe_collections() -> list[dict]:
    init_db()
    with connect() as conn:
        _ensure_swipe_tables(conn)
        rows = conn.execute(
            """SELECT c.*, COUNT(i.id) AS item_count
               FROM swipe_collections c
               LEFT JOIN swipe_items i ON i.collection_id = c.id
               GROUP BY c.id
               ORDER BY c.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def create_swipe_collection(name: str) -> int:
    init_db()
    with connect() as conn:
        _ensure_swipe_tables(conn)
        cur = conn.execute(
            "INSERT INTO swipe_collections (name, created_at) VALUES (?, ?)",
            (name.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def delete_swipe_collection(collection_id: int) -> None:
    with connect() as conn:
        _ensure_swipe_tables(conn)
        conn.execute("DELETE FROM swipe_items WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM swipe_collections WHERE id = ?", (collection_id,))


def add_swipe_item(collection_id: int, data: dict) -> int:
    init_db()
    with connect() as conn:
        _ensure_swipe_tables(conn)
        cur = conn.execute(
            """INSERT INTO swipe_items
               (collection_id, brand, niche, creative_path, landing_url, ad_text, notes, saved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                collection_id,
                data.get("brand", ""),
                data.get("niche", ""),
                data.get("creative_path", ""),
                data.get("landing_url", ""),
                (data.get("ad_text", "") or "")[:600],
                data.get("notes", ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def list_swipe_items(collection_id: int) -> list[dict]:
    with connect() as conn:
        _ensure_swipe_tables(conn)
        rows = conn.execute(
            "SELECT * FROM swipe_items WHERE collection_id = ? ORDER BY saved_at DESC",
            (collection_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_swipe_item(item_id: int) -> None:
    with connect() as conn:
        _ensure_swipe_tables(conn)
        conn.execute("DELETE FROM swipe_items WHERE id = ?", (item_id,))


def swipe_item_exists(collection_id: int, brand: str, creative_path: str) -> bool:
    with connect() as conn:
        _ensure_swipe_tables(conn)
        row = conn.execute(
            """SELECT 1 FROM swipe_items
               WHERE collection_id = ? AND brand = ? AND creative_path = ? LIMIT 1""",
            (collection_id, brand, creative_path),
        ).fetchone()
    return row is not None


# ============================================================
# Phase 16.4 — Seller-side store analytics (your OWN stores)
# ============================================================

_SELLER_STORES_SCHEMA = """
CREATE TABLE IF NOT EXISTS seller_stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,           -- 'shopee' | 'lazada' | 'tiktok_shop' | 'own_site'
    store_name TEXT NOT NULL,
    store_url TEXT,
    niche TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seller_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    units_sold INTEGER,
    revenue_php REAL,
    rating REAL,
    review_count INTEGER,
    follower_count INTEGER,
    notes TEXT,
    FOREIGN KEY(store_id) REFERENCES seller_stores(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_seller_snap_date ON seller_snapshots(snapshot_date DESC);
"""


def _ensure_seller_tables(conn) -> None:
    conn.executescript(_SELLER_STORES_SCHEMA)


def list_seller_stores() -> list[dict]:
    init_db()
    with connect() as conn:
        _ensure_seller_tables(conn)
        rows = conn.execute(
            "SELECT * FROM seller_stores ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def insert_seller_store(data: dict) -> int:
    init_db()
    with connect() as conn:
        _ensure_seller_tables(conn)
        cur = conn.execute(
            """INSERT INTO seller_stores
               (platform, store_name, store_url, niche, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data.get("platform", "shopee"),
                data.get("store_name", "").strip(),
                data.get("store_url", "").strip() or None,
                data.get("niche", "").strip() or None,
                data.get("notes", "").strip() or None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def delete_seller_store(store_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM seller_stores WHERE id = ?", (store_id,))


def add_seller_snapshot(store_id: int, data: dict) -> int:
    init_db()
    with connect() as conn:
        _ensure_seller_tables(conn)
        cur = conn.execute(
            """INSERT INTO seller_snapshots
               (store_id, snapshot_date, units_sold, revenue_php, rating,
                review_count, follower_count, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                store_id,
                data.get("snapshot_date", datetime.now().date().isoformat()),
                int(data.get("units_sold") or 0),
                float(data.get("revenue_php") or 0),
                float(data.get("rating") or 0) if data.get("rating") else None,
                int(data.get("review_count") or 0),
                int(data.get("follower_count") or 0),
                data.get("notes", "").strip() or None,
            ),
        )
        return cur.lastrowid


# ============================================================
# Phase 17.5/17.6 — Bestsellers (Shopee / Lazada / TikTok Shop)
# ============================================================

_BESTSELLERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bestsellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    niche TEXT,
    keyword TEXT,
    rank INTEGER,
    product_name TEXT,
    product_url TEXT,
    price_php REAL,
    units_sold INTEGER,
    rating REAL,
    review_count INTEGER,
    shop_name TEXT,
    thumbnail_url TEXT,
    captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bestsellers_date ON bestsellers(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_bestsellers_niche ON bestsellers(niche);
CREATE INDEX IF NOT EXISTS idx_bestsellers_platform ON bestsellers(platform);
"""


def _ensure_bestseller_tables(conn) -> None:
    conn.executescript(_BESTSELLERS_SCHEMA)


def insert_bestsellers(records: list[dict]) -> int:
    init_db()
    if not records:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for r in records:
        rows.append((
            r.get("platform", ""),
            r.get("snapshot_date", ""),
            r.get("niche", ""),
            r.get("keyword", ""),
            int(r.get("rank") or 0),
            r.get("product_name", ""),
            r.get("product_url", ""),
            float(r.get("price_php") or 0),
            int(r.get("units_sold") or 0),
            float(r.get("rating")) if r.get("rating") else None,
            int(r.get("review_count") or 0),
            r.get("shop_name", ""),
            r.get("thumbnail_url", ""),
            now,
        ))
    with connect() as conn:
        _ensure_bestseller_tables(conn)
        conn.executemany(
            """INSERT INTO bestsellers
               (platform, snapshot_date, niche, keyword, rank, product_name, product_url,
                price_php, units_sold, rating, review_count, shop_name, thumbnail_url, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def latest_bestsellers(platform: str | None = None, niche: str | None = None,
                       limit: int = 100) -> list[dict]:
    init_db()
    with connect() as conn:
        _ensure_bestseller_tables(conn)
        # Get most recent snapshot date
        latest_date_row = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM bestsellers"
        ).fetchone()
        if not latest_date_row or not latest_date_row["d"]:
            return []
        latest_date = latest_date_row["d"]
        sql = "SELECT * FROM bestsellers WHERE snapshot_date = ?"
        params: list = [latest_date]
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        if niche:
            sql += " AND niche = ?"
            params.append(niche)
        sql += " ORDER BY units_sold DESC, rank ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_seller_snapshots(store_id: int, limit: int = 50) -> list[dict]:
    with connect() as conn:
        _ensure_seller_tables(conn)
        rows = conn.execute(
            """SELECT * FROM seller_snapshots
               WHERE store_id = ?
               ORDER BY snapshot_date DESC
               LIMIT ?""",
            (store_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def backfill_categorization(run_id: int | None = None) -> dict:
    """Populate category + sub_category + location for ads missing them.

    If run_id is given, only that run is processed; otherwise ALL ads in the DB.
    Uses categorization.classify() and location_detector.detect_location() —
    both keyword-based, fast, no API costs. Never overwrites existing values.
    Returns: {processed, updated_cat, updated_sub, updated_loc}
    """
    import categorization
    import location_detector
    out = {"processed": 0, "updated_cat": 0, "updated_sub": 0, "updated_loc": 0}
    with connect() as conn:
        if run_id is None:
            rows = conn.execute(
                """SELECT library_id, run_id, ad_text, niche, landing_url, geo_signal,
                          category, sub_category, location
                   FROM ads"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT library_id, run_id, ad_text, niche, landing_url, geo_signal,
                          category, sub_category, location
                   FROM ads WHERE run_id = ?""",
                (run_id,),
            ).fetchall()

        for r in rows:
            out["processed"] += 1
            updates: dict = {}
            # Only fill if currently NULL/empty — never overwrite manual edits.
            if not r["category"] or not r["sub_category"]:
                cat, sub = categorization.classify(
                    r["ad_text"] or "", r["niche"] or "",
                )
                if cat and not r["category"]:
                    updates["category"] = cat
                    out["updated_cat"] += 1
                if sub and not r["sub_category"]:
                    updates["sub_category"] = sub
                    out["updated_sub"] += 1
            if not r["location"]:
                loc = location_detector.detect_location(
                    r["ad_text"] or "", r["landing_url"] or "",
                )
                if loc is None and r["geo_signal"] == "ph-confident":
                    loc = "PH-wide"
                if loc:
                    updates["location"] = loc
                    out["updated_loc"] += 1
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE ads SET {set_clause} WHERE library_id = ? AND run_id = ?",
                    list(updates.values()) + [r["library_id"], r["run_id"]],
                )
    return out


def dedupe_run_ads(run_id: int) -> dict:
    """Remove duplicate library_id rows within a single run, keeping the canonical version.

    Meta sometimes returns the same library_id under different brand attributions.
    Strategy:
      - For each library_id with >1 row in this run:
        - Keep the row with the MOST-FREQUENT brand name across the whole DB
        - Delete the others
    Returns: {duplicates_found, duplicates_removed, kept_canonical}
    """
    out = {"duplicates_found": 0, "duplicates_removed": 0, "kept_canonical": 0}
    with connect() as conn:
        # Find library_ids with multiple rows in this run
        dup_libs = [
            r["library_id"] for r in conn.execute(
                """SELECT library_id, COUNT(*) AS n FROM ads
                   WHERE run_id = ? AND library_id IS NOT NULL AND library_id <> ''
                   GROUP BY library_id HAVING n > 1""",
                (run_id,),
            ).fetchall()
        ]
        out["duplicates_found"] = len(dup_libs)
        if not dup_libs:
            return out

        # For each dup, pick the canonical brand (most frequent across DB) then delete others
        for lib_id in dup_libs:
            # Get all rows for this library_id in this run, with brand
            rows = conn.execute(
                """SELECT rowid, brand, page_name FROM ads
                   WHERE run_id = ? AND library_id = ?""",
                (run_id, lib_id),
            ).fetchall()
            if len(rows) < 2:
                continue
            # Count brand frequency across the WHOLE DB to pick canonical
            brands = [(r["brand"] or r["page_name"] or "").strip().lower() for r in rows]
            brand_global_counts: dict[str, int] = {}
            for b in set(brands):
                if not b:
                    continue
                c = conn.execute(
                    "SELECT COUNT(*) AS n FROM ads WHERE LOWER(COALESCE(brand,page_name)) = ?",
                    (b,),
                ).fetchone()["n"]
                brand_global_counts[b] = c
            # Find the rowid whose brand has highest global count
            best_rowid = rows[0]["rowid"]
            best_score = -1
            for r in rows:
                b = (r["brand"] or r["page_name"] or "").strip().lower()
                score = brand_global_counts.get(b, 0)
                if score > best_score:
                    best_score = score
                    best_rowid = r["rowid"]
            # Delete the others
            delete_ids = [r["rowid"] for r in rows if r["rowid"] != best_rowid]
            if delete_ids:
                placeholders = ",".join("?" for _ in delete_ids)
                conn.execute(
                    f"DELETE FROM ads WHERE rowid IN ({placeholders})",
                    delete_ids,
                )
                out["duplicates_removed"] += len(delete_ids)
            out["kept_canonical"] += 1

    return out


def latest_run_id(only_meta: bool = False) -> int | None:
    with connect() as conn:
        if only_meta:
            row = conn.execute(
                """SELECT r.run_id FROM runs r
                   JOIN ads a ON a.run_id = r.run_id
                   WHERE COALESCE(r.source,'') <> 'tiktok'
                   GROUP BY r.run_id
                   ORDER BY r.run_id DESC LIMIT 1"""
            ).fetchone()
        else:
            row = conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
        return row["run_id"] if row else None


def ads_for_run(run_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT a.*, c.media_path AS creative_path
               FROM ads a LEFT JOIN creatives c ON a.library_id = c.library_id
               WHERE a.run_id = ? ORDER BY a.score DESC""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def consecutive_runs_for_ad(library_id: str) -> int:
    """How many of the most recent runs has this library_id appeared in (consecutively)?"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT run_id FROM ads WHERE library_id = ? ORDER BY run_id DESC",
            (library_id,),
        ).fetchall()
        if not rows:
            return 0
        all_runs = [r["run_id"] for r in conn.execute(
            "SELECT run_id FROM runs ORDER BY run_id DESC"
        ).fetchall()]
        ad_runs = {r["run_id"] for r in rows}
        consecutive = 0
        for rid in all_runs:
            if rid in ad_runs:
                consecutive += 1
            else:
                break
        return consecutive


def brand_history(brand: str, limit_runs: int = 30) -> list[dict]:
    """Per-run summary for a brand across recent runs."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.run_id, r.started_at, COUNT(a.library_id) AS ad_count,
                      SUM(a.is_active) AS active_count, MAX(a.days_running) AS max_days
               FROM runs r LEFT JOIN ads a ON a.run_id = r.run_id AND a.brand = ?
               GROUP BY r.run_id
               ORDER BY r.run_id DESC LIMIT ?""",
            (brand, limit_runs),
        ).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    with connect() as conn:
        total_runs = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        total_ads = conn.execute("SELECT COUNT(*) c FROM ads").fetchone()["c"]
        unique_ads = conn.execute("SELECT COUNT(DISTINCT library_id) c FROM ads").fetchone()["c"]
        unique_brands = conn.execute("SELECT COUNT(DISTINCT brand) c FROM ads WHERE brand <> ''").fetchone()["c"]
        creatives_count = conn.execute("SELECT COUNT(*) c FROM creatives").fetchone()["c"]
        tiktok_count = conn.execute("SELECT COUNT(*) c FROM tiktok_ads").fetchone()["c"]
        enriched_count = conn.execute("SELECT COUNT(*) c FROM ads WHERE mp_enriched_at IS NOT NULL AND mp_enriched_at <> ''").fetchone()["c"]
    return {
        "total_runs": total_runs,
        "total_ad_observations": total_ads,
        "unique_library_ids": unique_ads,
        "unique_brands": unique_brands,
        "creatives_saved": creatives_count,
        "marketplace_enriched": enriched_count,
        "tiktok_ads": tiktok_count,
    }


def insert_tiktok_ads(run_id: int, ads: list[dict]) -> int:
    if not ads:
        return 0
    init_db()
    rows = []
    for a in ads:
        rows.append((
            a.get("ad_id", ""),
            run_id,
            a.get("captured_at", ""),
            a.get("country", "PH"),
            a.get("industry", ""),
            a.get("advertiser", ""),
            a.get("title", ""),
            a.get("description", ""),
            a.get("cta", ""),
            int(a.get("likes") or 0),
            int(a.get("comments") or 0),
            int(a.get("shares") or 0),
            int(a.get("plays") or 0),
            float(a.get("ctr") or 0),
            int(a.get("duration_seconds") or 0),
            a.get("first_shown", ""),
            a.get("last_shown", ""),
            a.get("thumbnail_url", ""),
            a.get("video_url", ""),
            a.get("detail_url", ""),
            a.get("raw_text", "")[:2000],
        ))
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO tiktok_ads
               (ad_id, run_id, captured_at, country, industry, advertiser, title, description, cta,
                likes, comments, shares, plays, ctr, duration_seconds,
                first_shown, last_shown, thumbnail_url, video_url, detail_url, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return len(rows)


def tiktok_ads_for_run(run_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tiktok_ads WHERE run_id = ? ORDER BY likes DESC", (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def latest_tiktok_run_id() -> int | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT run_id FROM runs WHERE source = 'tiktok' ORDER BY run_id DESC LIMIT 1"""
        ).fetchone()
        return row["run_id"] if row else None
