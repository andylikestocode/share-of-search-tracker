# BRUNT Share of Search Tracker

Monthly Share of Search dashboard powered by Google Keyword Planner CSV exports.

## How it works

```
You (15 min/month):
  Keyword Planner UI  →  Export CSV
                          ↓
                  python src/validate_csv.py  (catches format issues locally)
                          ↓
                  Commit to data/YYYY-MM.csv

Automated (on every CSV commit):
  GitHub Action  →  src/pipeline.py  →  artifacts/*.csv
                                       ↓
                              Streamlit dashboard
```

---

## One-time setup

### Step 1 — Create the repo

```bash
gh repo create share-of-search-tracker --private --source=. --push
```

Or do it via the web UI: create empty private repo, drag-and-drop the zip contents.

### Step 2 — Save your keyword list in Keyword Planner

1. Go to Google Ads → Tools → Keyword Planner → Discover new keywords
2. Paste the full keyword list from `config/keywords.yaml` (one per line)
3. Click **Get results**
4. Save the plan: top right → **Save plan** → name it "BRUNT SoS Tracker"

Now every month you re-open the same plan instead of pasting again.

### Step 3 — First data pull

1. Open your saved plan in Keyword Planner
2. Use the **"Historical metrics"** tab (not Forecasts)
3. Set date range to **Last 12 months**
4. Top right → **Download keyword ideas** → CSV (.csv)
5. **Validate it locally first:**
   ```bash
   python src/validate_csv.py ~/Downloads/Keyword_Stats_xxx.csv
   ```
   This catches encoding issues, bucketed volumes, missing keywords, and bad filenames before you push.
6. If validation passes, rename and commit:
   ```bash
   mv ~/Downloads/Keyword_Stats_xxx.csv data/2026-05.csv
   git add data/2026-05.csv
   git commit -m "data: May 2026 keyword volumes"
   git push
   ```
7. GitHub Action triggers automatically. Check the **Actions** tab to watch it run.

### Step 4 — Streamlit dashboard

1. Go to https://share.streamlit.io
2. Sign in with GitHub, authorize access to the repo
3. **New app** → pick the repo, branch `main`, main file path `dashboard/app.py`
4. Deploy. Takes ~2 minutes.
5. Bookmark the URL.

---

## Monthly workflow (your 15 minutes)

On the first Monday of each month:

1. Open the saved plan in Keyword Planner
2. Make sure date range is **Last 12 months** (rolling)
3. **Download keyword ideas** → CSV
4. Validate locally:
   ```bash
   python src/validate_csv.py ~/Downloads/Keyword_Stats_xxx.csv
   ```
5. Move + commit:
   ```bash
   mv ~/Downloads/Keyword_Stats_xxx.csv data/2026-05.csv
   git add data/2026-05.csv
   git commit -m "data: May 2026"
   git push
   ```
6. Action runs, dashboard updates. Done.

If you don't want to use git CLI, you can also upload via the GitHub web UI: navigate to `data/` → **Add file** → **Upload files** → drag the renamed file in. Still validate locally first though.

---

## Editing the keyword set

Edit `config/keywords.yaml`. After pushing, also update your saved Keyword Planner plan to include the new keywords — the pipeline only sees what's in the CSV.

Keywords in the CSV but not in `keywords.yaml` are ignored with a warning. Keywords in `keywords.yaml` but not in the CSV are skipped silently. The validator flags both.

---

## Run locally to test

```bash
pip install -r requirements.txt
python src/pipeline.py             # builds artifacts/
streamlit run dashboard/app.py     # local dashboard at http://localhost:8501
```

---

## Important notes on Keyword Planner data

- **It's monthly, not weekly.** The cadence of this whole system is monthly.
- **Low-spend accounts get bucketed ranges** (e.g. "1K–10K" instead of "4,400"). BRUNT's ad spend should clear the threshold for exact numbers — but if you see bucketed data, the validator will flag it and you should export from a higher-spend account.
- **It's Google's data only**, not all-search-engines. For BRUNT's tradesperson audience this is ~92%+ of US search demand, so it's a fine proxy.
- **YoY deltas need 13+ months of CSVs** before they populate — that's why pulling the full last-12-months range on every export matters (overlapping months let the pipeline backfill history).

---

## File layout

```
share-of-search-tracker/
├── config/
│   └── keywords.yaml          # taxonomy — edit this
├── data/
│   └── YYYY-MM.csv            # your monthly drops
├── src/
│   ├── pipeline.py            # CSV → metrics
│   └── validate_csv.py        # run before committing
├── dashboard/
│   └── app.py                 # Streamlit dashboard
├── artifacts/                 # auto-generated, committed by Action
│   ├── sos_history.csv
│   ├── category_summary.csv
│   ├── trade_opportunity.csv
│   └── all_keywords_tagged.csv
├── .github/workflows/
│   └── update.yml             # triggers on data/ or config/ changes
├── requirements.txt
└── README.md
```
