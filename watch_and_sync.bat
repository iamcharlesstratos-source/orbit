@echo off
REM ============================================================
REM  Orbit AUTO-SYNC  |  watches for changes, auto-deploys to HF
REM  Double-click to START. Leave the window open.
REM  Every file change auto-uploads to your live Space.
REM  Close the window to STOP.
REM ============================================================
cd /d "%~dp0"
title Orbit Auto-Sync (keep open)
echo.
echo  Starting Orbit auto-sync watcher...
echo  Leave this window open. Close it to stop.
echo.
python watch_and_sync.py
echo.
echo  Watcher stopped. Press any key to close.
pause >nul
