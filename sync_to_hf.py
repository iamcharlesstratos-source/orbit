"""One-click sync of Orbit to Hugging Face Spaces.

Double-click sync_to_hf.bat (or run `python sync_to_hf.py`) to push ALL current
code + data to your HF Space. HF computes the diff and only uploads changed files.

Setup (one-time):
  1. Create a WRITE token at https://huggingface.co/settings/tokens
     (click "New token" -> name it "orbit-sync" -> type: Write -> Generate)
  2. Save it into a file named `.hf_token` in this folder (just paste the token).
     OR set the env var HF_TOKEN.
  3. Make sure SPACE_ID below matches your Space.

After that, every time we revise code or you scrape new data:
  -> double-click sync_to_hf.bat  ->  the live Space updates in ~1 minute.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ----- CONFIG: change this if your Space name is different -----
SPACE_ID = "product-hunter-ai/orbit"   # <username>/<space-name>
# ---------------------------------------------------------------

# Files / folders NEVER uploaded (local-only, huge, or secret)
IGNORE_PATTERNS = [
    "creatives/*", "creatives/**",
    "output/*", "output/**",
    "logs/*", "logs/**",
    "__pycache__/*", "**/__pycache__/**",
    "*.pyc", "*.pyo",
    ".git/*", ".git/**",
    ".streamlit/secrets.toml",
    ".env", "*.pem", "*.key",
    ".hf_token",
    ".onboarding_seen", ".inbox_last_seen",
    ".activity_log.json", ".page_hints_seen.json",
    "run_daily.ps1",
    "db/agent.db-journal", "db/agent.db-wal", "db/agent.db-shm",
    "sync_to_hf.py", "sync_to_hf.bat",   # no need to ship the sync tool itself
    "watch_and_sync.py", "watch_and_sync.bat",
    "*.bak",
    "*_preview.html",            # local design/layout mockups, not part of the app
    "*_silver_backup.png",       # logo backup, local only
    "*_brass_full.png",          # pre-crop logo backup, local only
]


def _get_token() -> str | None:
    # 1) .hf_token file
    tok_file = ROOT / ".hf_token"
    if tok_file.exists():
        tok = tok_file.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    # 2) env var
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _refresh_seed() -> None:
    """Regenerate db/seed.sql from the current agent.db so the cloud can rebuild
    even if the binary upload ever fails. Cheap insurance."""
    src = ROOT / "db" / "agent.db"
    out = ROOT / "db" / "seed.sql"
    if not src.exists():
        print("  (no db/agent.db yet — skipping seed refresh)")
        return
    try:
        conn = sqlite3.connect(src)
        with open(out, "w", encoding="utf-8") as f:
            for line in conn.iterdump():
                f.write(line + "\n")
        conn.close()
        print(f"  Refreshed db/seed.sql ({out.stat().st_size/1024/1024:.2f} MB)")
    except Exception as e:
        print(f"  (seed refresh skipped: {e})")


def main() -> int:
    print("=" * 56)
    print(" Orbit -> Hugging Face Spaces sync")
    print("=" * 56)

    # Ensure huggingface_hub is available
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("\nInstalling huggingface_hub (one-time)...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
                       check=False)
        try:
            from huggingface_hub import HfApi
        except ImportError:
            print("ERROR: could not install huggingface_hub. "
                  "Run: pip install huggingface_hub")
            return 1

    token = _get_token()
    if not token:
        print("\nERROR: No Hugging Face token found.")
        print("  1. Make a WRITE token: https://huggingface.co/settings/tokens")
        print("  2. Paste it into a file named  .hf_token  in this folder.")
        print("     (or set the HF_TOKEN environment variable)")
        return 1

    print(f"\nSpace: {SPACE_ID}")
    print("Refreshing data seed...")
    _refresh_seed()

    print("\nUploading changed files to Hugging Face (diff-only, may take a minute)...")
    api = HfApi(token=token)
    try:
        api.upload_folder(
            folder_path=str(ROOT),
            repo_id=SPACE_ID,
            repo_type="space",
            ignore_patterns=IGNORE_PATTERNS,
            commit_message="Sync from local desktop",
        )
    except Exception as e:
        print(f"\nERROR during upload: {type(e).__name__}: {e}")
        print("\nCommon fixes:")
        print("  - Token must have WRITE permission")
        print("  - SPACE_ID must match exactly (check sync_to_hf.py)")
        print("  - The Space must already exist on huggingface.co")
        return 1

    print("\n" + "=" * 56)
    print(" DONE! Your Space is rebuilding now (~1-2 min).")
    print(f" Open: https://huggingface.co/spaces/{SPACE_ID}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
