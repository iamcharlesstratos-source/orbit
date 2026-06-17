@echo off
REM Double-click to open the Product Research dashboard in your browser.
cd /d "%~dp0"
python -m streamlit run app.py
