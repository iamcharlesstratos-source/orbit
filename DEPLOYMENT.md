# Orbit — Streamlit Cloud Deployment Guide

Put your Orbit instance online for your team / clients to access at
`https://your-orbit-name.streamlit.app`.

**What you get:**
- Public URL (or password-gated if you set `APP_PASSWORD`)
- Auto-redeploys when you `git push`
- Free tier (~1 GB RAM, sleeps on inactivity but wakes on visit)

**What you LOSE in cloud mode:**
- ❌ Scraping — Playwright can't run on Streamlit Cloud. **You scrape locally**, then commit the updated `orbit.db` to refresh the cloud view.
- ❌ Daily scheduler — that's Windows Task Scheduler only.
- ❌ BIR Receipt OCR + Copy Studio AI work fine (use Claude API).

The cloud install is essentially a **view-only dashboard** of data you scraped locally.

---

## ✅ One-time setup (15 minutes)

### 1. Create a GitHub repo

```powershell
cd "C:\Users\ADMIN\Documents\Product Research Agent"
git init
git add .
git status                            # verify .gitignore is excluding orbit.db, secrets, etc.
git commit -m "Initial Orbit commit"
```

Then on github.com:
- New repository → name it (e.g. `orbit-prod`) → **Private** (recommended)
- Copy the push commands:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/orbit-prod.git
git branch -M main
git push -u origin main
```

### 2. Decide: commit `orbit.db` or not?

The `.gitignore` excludes `orbit.db` by default (it's 1-10 MB and frequently changes).

**Recommended for a view-only cloud:** include the DB so the cloud has your data.

```powershell
# Edit .gitignore — remove or comment out the `orbit.db` line, then:
git add orbit.db
git commit -m "Include current DB snapshot"
git push
```

Each time you want to refresh the cloud with new data:
```powershell
python main.py             # scrape locally
git add orbit.db
git commit -m "Refresh data $(Get-Date -Format yyyy-MM-dd)"
git push                   # Streamlit Cloud auto-redeploys in ~1 minute
```

### 3. Deploy to Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub
2. Click **New app**
3. Repository: `YOUR_USERNAME/orbit-prod`
   Branch: `main`
   Main file path: `app.py`
4. Click **Advanced settings** → **Secrets** → paste:

```toml
ANTHROPIC_API_KEY = "sk-ant-your-actual-key"

# Optional — only if you want to lock the app behind a shared password:
# APP_PASSWORD = "your-team-password"
```

5. Click **Deploy**

Wait ~3 minutes for the first build. You'll get a URL like:
`https://orbit-prod-YOUR_USERNAME.streamlit.app`

---

## 🔒 Lock it behind a password (optional)

In the Streamlit Cloud secrets editor, add:

```toml
APP_PASSWORD = "your-shared-password-here"
```

Save → app will redeploy. Now visitors see a login screen before the dashboard.

To remove the gate: delete the `APP_PASSWORD` line and save.

---

## 🔄 Refreshing data after a local scrape

Two options:

### Option A — Commit the DB to git (simplest)
```powershell
python main.py             # local scrape
git add orbit.db
git commit -m "Data refresh $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git push
```
Cloud auto-redeploys in ~60 seconds.

### Option B — Manual upload via Streamlit Cloud UI
- Visit your app's Streamlit Cloud admin page
- Use the file-explorer pane to drop the new `orbit.db`
- Click **Reboot app**

(Less convenient — use Option A.)

---

## 🚨 Common issues

**"This app is taking too long to load"**
Cloud free-tier apps sleep after 7 days of inactivity. First wake takes ~30s.

**"ModuleNotFoundError"**
A dependency is missing from `requirements.txt`. Check the Streamlit Cloud
build log → add the missing pip name → push.

**"Permission denied: orbit.db"**
The DB is read-only on cloud. Any edit attempt (star a brand, add testing
product, etc.) will fail in cloud mode. This is expected — do those locally.

**Streamlit shows old data after I pushed**
- Verify the new commit is on `main` (Streamlit Cloud only tracks one branch)
- In the cloud admin, click **Reboot app**
- Check the build log for errors

---

## 🌐 Custom domain (paid Streamlit tier or Cloudflare)

Free tier gives you `*.streamlit.app`. To use `app.yourbrand.com`:

1. **Paid Streamlit Teams plan** — built-in custom domain support
2. **DIY via Cloudflare** — set up a CNAME pointing to your `*.streamlit.app`,
   then put it behind a Cloudflare Worker for path-rewriting. More work.

---

## 📊 What works in cloud vs local

| Feature                              | Local | Cloud |
|--------------------------------------|:-----:|:-----:|
| View all dashboards                  | ✅    | ✅    |
| Click brand row → modal              | ✅    | ✅    |
| Star / set status / notes            | ✅    | ⚠️ ephemeral |
| Copy Studio (Claude)                 | ✅    | ✅    |
| AI brand angle reports               | ✅    | ✅    |
| FDA compliance check                 | ✅    | ✅    |
| Image prompt + landing page gen      | ✅    | ✅    |
| BIR receipt OCR (Claude Vision)      | ✅    | ✅    |
| Brand timeline + cluster             | ✅    | ✅    |
| Testing pipeline                     | ✅    | ⚠️ ephemeral |
| **Run scrape**                       | ✅    | ❌    |
| **Daily scheduler**                  | ✅    | ❌    |
| Marketplace bestsellers scrape       | ✅    | ❌    |

⚠️ "Ephemeral" — edits on the cloud version are lost on next redeploy because the DB resets to whatever's in git. Use the cloud for VIEWING; do edits locally.

---

## 🎯 Recommended workflow

1. **Local laptop**: run daily scrape (via Task Scheduler from Phase 15.1)
2. **Each morning**: glance at fresh data on your laptop, do research
3. **When you find a winner**: star brand + add notes locally
4. **End of week**: commit + push the updated DB so the team can see latest
5. **Team / clients**: visit your `*.streamlit.app` URL to review winners + reports

That's it. You're online.
