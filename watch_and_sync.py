"""Auto-watch Orbit files and push to Hugging Face Spaces on every change.

Start it ONCE (double-click watch_and_sync.bat), leave the window open, and it
will automatically sync to your live Space whenever a tracked file changes —
no manual upload, no double-clicking each time.

How it works:
  - Polls the project folder every few seconds (no extra dependencies).
  - When it sees a change to any .py / .json / .toml / db file, it waits a few
    seconds for things to settle (debounce), then pushes only the changed files
    to HF. HF rebuilds the Space automatically (~1-2 min).

Setup (one-time): same as sync_to_hf.py — you need a WRITE token in `.hf_token`.

Stop it: just close the window (or press Ctrl+C).
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Reuse the sync logic + config from sync_to_hf.py
try:
    import sync_to_hf
except Exception as e:
    print(f"ERROR: could not import sync_to_hf.py ({e}). "
          "Make sure both files are in the same folder.")
    raise SystemExit(1)

POLL_SECONDS = 3        # how often to check for changes
DEBOUNCE_SECONDS = 4    # wait this long after the LAST change before syncing

# Which files to watch (extensions + the DB)
WATCH_EXTS = {".py", ".json", ".toml", ".md", ".txt"}
WATCH_DB = ROOT / "db" / "agent.db"

# Folders to skip when scanning
SKIP_DIRS = {"__pycache__", ".git", "creatives", "output", "logs", ".streamlit"}
# (we still watch .streamlit/config.toml explicitly below)


def _tracked_files() -> list[Path]:
    files: list[Path] = []
    for p in ROOT.rglob("*"):
        # skip directories + skip-listed folders
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            # but allow .streamlit/config.toml
            if not (p.name == "config.toml" and p.parent.name == ".streamlit"):
                continue
        if p.suffix.lower() in WATCH_EXTS:
            files.append(p)
    if WATCH_DB.exists():
        files.append(WATCH_DB)
    return files


def _snapshot() -> dict[str, float]:
    """Map of file path -> mtime for all tracked files."""
    snap: dict[str, float] = {}
    for f in _tracked_files():
        try:
            snap[str(f)] = f.stat().st_mtime
        except OSError:
            pass
    return snap


def _changed(old: dict[str, float], new: dict[str, float]) -> list[str]:
    changed = []
    for path, mt in new.items():
        if path not in old or old[path] != mt:
            changed.append(path)
    # also detect deletions
    for path in old:
        if path not in new:
            changed.append(path)
    return changed


def main() -> int:
    # Verify token up front so we fail fast
    if not sync_to_hf._get_token():
        print("=" * 56)
        print(" SETUP NEEDED — no Hugging Face token found.")
        print("=" * 56)
        print(" 1. Make a WRITE token: https://huggingface.co/settings/tokens")
        print(" 2. Paste it into a file named  .hf_token  in this folder.")
        print(" 3. Re-run this watcher.")
        return 1

    print("=" * 56)
    print(" Orbit AUTO-SYNC watcher")
    print(f" Space: {sync_to_hf.SPACE_ID}")
    print("=" * 56)
    print(" Watching for changes... (leave this window open)")
    print(" Every time a file changes, it auto-uploads to the cloud.")
    print(" Close this window to stop.\n")

    last_snap = _snapshot()
    print(f" Tracking {len(last_snap)} files. Ready.\n")

    pending_since: float | None = None

    while True:
        try:
            time.sleep(POLL_SECONDS)
            now_snap = _snapshot()
            diffs = _changed(last_snap, now_snap)

            if diffs:
                # Something changed — (re)start the debounce timer
                names = ", ".join(Path(d).name for d in diffs[:5])
                extra = f" (+{len(diffs)-5} more)" if len(diffs) > 5 else ""
                print(f" [change] {names}{extra}")
                last_snap = now_snap
                pending_since = time.time()
                continue

            # No new changes this tick — check if we should fire the sync
            if pending_since is not None:
                if time.time() - pending_since >= DEBOUNCE_SECONDS:
                    print("\n" + "-" * 56)
                    print(" Changes settled — syncing to Hugging Face now...")
                    print("-" * 56)
                    try:
                        sync_to_hf.main()
                    except Exception as e:
                        print(f" Sync error: {e}")
                    pending_since = None
                    # refresh snapshot (seed.sql gets regenerated during sync)
                    last_snap = _snapshot()
                    print("\n Watching for changes again...\n")
        except KeyboardInterrupt:
            print("\n Stopped. Bye!")
            return 0
        except Exception as e:
            print(f" Watcher hiccup (continuing): {e}")
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
