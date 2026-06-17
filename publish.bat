@echo off
REM One-click publish: push local changes to GitHub.
REM Streamlit Community Cloud auto-redeploys the live site within ~1-2 minutes.
cd /d "%~dp0"
echo ============================================================
echo  Publishing Orbit to GitHub...
echo ============================================================
git add -A
git commit -m "Update from desktop" || echo (nothing new to commit)
git push
echo.
echo Done. If connected to Streamlit Cloud, the live site redeploys in ~1-2 min.
pause
