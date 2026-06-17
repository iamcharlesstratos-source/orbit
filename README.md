---
title: Orbit Product Research Hunter
emoji: 🛰️
colorFrom: gray
colorTo: yellow
sdk: streamlit
sdk_version: 1.57.0
app_file: app.py
pinned: false
---

# Orbit — Product Research Hunter

AI-powered Philippine ecommerce ad-research platform. Scrapes Meta Ads Library,
classifies winners, tracks product testing, and generates Taglish ad copy.

**Live view-only deployment** — data is scraped locally then synced here.

## Features
- FB Ads Library winner tracking with PH-confidence + niche relevance scoring
- Brand timeline, cluster detection (same-operator unmasking)
- FDA compliance checker (flags illegal PH medical claims)
- AI Copy Studio (Taglish / Bisaya / Ilocano / Hiligaynon)
- Brand angle reports, hook predictor, image prompts, landing page generator
- Product testing pipeline with ROI tracker + BIR receipt OCR
- Courier rate calculator (J&T / LBC / Ninja Van)
- Marketplace bestsellers, seller-side store analytics

## Notes
- Scraping requires the local desktop install (Playwright can't run on hosted clouds).
- AI features need an `ANTHROPIC_API_KEY` set in Space secrets.
- Set `APP_PASSWORD` in Space secrets to gate access behind a login.
