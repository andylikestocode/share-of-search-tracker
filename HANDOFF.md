# HANDOFF

## Current state
Share-of-Boot-Intent-Search tracker for BRUNT vs. competitor work-boot brands. Lives in this repo (`share-of-search-tracker`); dashboard is a local Streamlit app (`streamlit run dashboard/app.py`). Monthly workflow: export Google Ads Keyword Planner CSV → drop into `data/` → commit/push → pipeline ingests it and refreshes artifacts. Latest data month committed: see most recent file in `data/`. Last meaningful change shipped: Keyword Detail section grouped by category added to the dashboard (commit `eaa5cfa`).

## Architecture in 5 bullets
- **Data source:** Manual CSV export from Google Keyword Planner (12 monthly "Searches" columns per keyword). No API.
- **Pipeline trigger:** Push to `data/*.csv` runs the pipeline; outputs are committed back via CI.
- **Outputs:** `artifacts/` (long-form parquet/CSV consumed by the dashboard) + Streamlit dashboard in `dashboard/app.py`.
- **Key files:** `config/keywords.yaml` (brand → keyword mapping + category), `src/pipeline.py` (ingest + share computation), `src/validate_csv.py` (schema/format checks pre-ingest), `dashboard/app.py` (Streamlit UI).
- **Schedule:** Monthly cadence, ~15 min of manual effort, ~1.5 month data lag from Google.

## Methodology note
The metric is **Share of Boot-Intent Search**, not share of brand search. We track `"carhartt boots"` not `"carhartt"`, because BRUNT competes for *boot demand* — not jacket, coverall, or general Carhartt demand. Using bare brand names would inflate Carhartt/Timberland (huge non-boot brand pull) and make BRUNT look invisible by comparison. Boot-intent keywords isolate the demand pool we actually compete in. This is the single decision that makes the numbers meaningful; do not "fix" the keyword list by adding bare brand terms without re-reading this.

## v2 backlog (ordered by ROI)
1. **Google Search Console integration** — pull BRUNT impressions/clicks/CTR/position per keyword. Turns this from "competitive landscape view" into "BRUNT performance view." Est. 45 min.
2. **Email digest alerts** when MoM share shifts >1pt for any tracked competitor. Replaces the Slack notifier we couldn't get connected.
3. **Investigate Oct–Nov 2025 BRUNT SoBIS spike** (+2–3pt) — find the marketing driver in the calendar; assess whether it's repeatable.
4. **Wholesale-partner branded-bidding monitor** — adjacent but separate project.

## Known limitations
- Monthly cadence only — Keyword Planner doesn't expose weekly data.
- ~1.5 month data lag from Google.
- YoY deltas won't populate until **March 2027** (need 13 months of CSV history).
- Carhartt and Timberland appear smaller than their true brand size because we use boot-intent keywords. **Intentional** — see methodology note.

## Open decisions for next session
- Expand the keyword set with multi-variant boot terms per brand (e.g. `carhartt mens boots`, `carhartt work boots`)?
- Add a "biggest movers" callout card to the dashboard?
- Set up email alerts now, or wait 2–3 cycles to learn what's actually worth alerting on?
