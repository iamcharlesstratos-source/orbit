@echo off
REM ============================================================
REM  Orbit -> Hugging Face Spaces  |  ONE-CLICK SYNC
REM  Double-click this file to push all code + data to the cloud.
REM ============================================================
cd /d "%~dp0"
echo.
echo  Syncing Orbit to Hugging Face Spaces...
echo.
python sync_to_hf.py
echo.
echo  ------------------------------------------------------------
echo  Press any key to close this window.
pause >nul
