"""Save ad creatives (image / video) to disk so winners can be studied visually."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

import db

log = logging.getLogger("pra.creatives")

ROOT = Path(__file__).resolve().parent
CREATIVES_DIR = ROOT / "creatives"

# Conservative timeouts — these CDN URLs are signed and short-lived; fail fast if slow
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/*,video/*,*/*;q=0.8",
}


def _ext_for(media_type: str, url: str) -> str:
    if media_type == "video":
        for cand in (".mp4", ".webm", ".mov"):
            if cand in url.lower():
                return cand
        return ".mp4"
    # image — sniff from URL
    for cand in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if cand in url.lower():
            return cand
    return ".jpg"


def detect_media(card) -> tuple[str, str]:
    """Return (media_type, media_url) for an ad card. Empty strings if not found.

    Videos take priority over images — most winning PH ads are video.
    Blob URLs are skipped (browser-internal, can't be downloaded externally)."""
    try:
        videos = card.locator("video").all()
        for v in videos[:3]:
            src = v.get_attribute("src") or ""
            if src.startswith("http"):
                return ("video", src)
            try:
                source = v.locator("source").first
                src2 = source.get_attribute("src") or ""
                if src2.startswith("http"):
                    return ("video", src2)
            except Exception:
                pass
            # Also check poster (video thumbnail) — useful fallback
            poster = v.get_attribute("poster") or ""
            if poster.startswith("http"):
                # Still mark as video so user knows it's a video ad, even if we can only get poster
                return ("video", poster)
    except Exception:
        pass

    try:
        imgs = card.locator("img").all()
        best_src = ""
        best_area = 0
        for img in imgs[:25]:
            src = img.get_attribute("src") or ""
            if not src or not src.startswith("http"):
                continue
            # Skip profile pics, icons — they're usually <100px squares
            try:
                w = int(img.get_attribute("width") or 0)
                h = int(img.get_attribute("height") or 0)
            except ValueError:
                w = h = 0
            # Heuristic: prefer scontent-served Facebook CDN images (the actual ad creative)
            is_creative_cdn = "scontent" in src or "fbcdn" in src
            area = w * h
            if is_creative_cdn and area >= best_area:
                best_area = area
                best_src = src
        if best_src:
            return ("image", best_src)
    except Exception:
        pass

    return ("", "")


def download(library_id: str, media_type: str, url: str, force: bool = False) -> str | None:
    """Download a creative to creatives/<library_id>.<ext>. Returns relative path or None."""
    if not url or not media_type:
        return None
    if not force and db.has_creative(library_id):
        return None

    CREATIVES_DIR.mkdir(exist_ok=True)
    ext = _ext_for(media_type, url)
    out_path = CREATIVES_DIR / f"{library_id}{ext}"
    rel = f"creatives/{library_id}{ext}"

    try:
        with requests.get(url, headers=_HEADERS, timeout=15, stream=True) as r:
            r.raise_for_status()
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    f.write(chunk)
        size = out_path.stat().st_size
        if size < 1024:
            # Tiny response — probably an error page or expired signed URL
            out_path.unlink(missing_ok=True)
            log.debug("download too small (%d bytes) for %s — discarded", size, library_id)
            return None
        db.upsert_creative(library_id, media_type, rel, url, size)
        return rel
    except requests.RequestException as e:
        log.debug("download failed for %s: %s", library_id, e)
        return None
    except Exception as e:
        log.debug("download error for %s: %s", library_id, e)
        return None
