"""
Share of Search pipeline - Keyword Planner CSV ingestion.

Reads monthly Keyword Planner CSV exports from data/, builds a unified
history.csv, computes SoS metrics, and writes artifacts for the dashboard.

CSV naming convention: data/YYYY-MM.csv  (e.g., data/2026-05.csv)

Keyword Planner export columns we care about:
  - Keyword
  - Avg. monthly searches
  - Three month change
  - YoY change
"""
import re
import logging
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "keywords.yaml"
ARTIFACTS = ROOT / "artifacts"

CSV_NAME_RE = re.compile(r"^(\d{4})-(\d{2})\.csv$")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def parse_keyword_planner_csv(path: Path) -> pd.DataFrame:
    """
    Google Keyword Planner CSVs have a non-standard header.
    First 2 rows are metadata (date range, currency). Actual headers on row 3.
    Encoding is UTF-16 with tabs. We auto-detect and normalize.
    """
    # Keyword Planner exports as UTF-16 tab-delimited by default
    encodings = ["utf-16", "utf-8", "utf-8-sig"]
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(path, sep="\t", encoding=enc, skiprows=2)
            if "Keyword" in df.columns:
                break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue

    # Fallback: try comma-delimited (if user re-saved as CSV)
    if df is None or "Keyword" not in df.columns:
        for enc in encodings:
            try:
                df = pd.read_csv(path, encoding=enc, skiprows=2)
                if "Keyword" in df.columns:
                    break
            except Exception:
                continue

    if df is None or "Keyword" not in df.columns:
        raise RuntimeError(f"Could not parse {path.name}. Expected 'Keyword' column.")

    # Standardize column names — Keyword Planner uses variations
    rename_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == "keyword":
            rename_map[c] = "keyword"
        elif "avg" in cl and "search" in cl:
            rename_map[c] = "avg_monthly_searches"
        elif "three month" in cl or "3 month" in cl:
            rename_map[c] = "three_month_change"
        elif "yoy" in cl or "year over year" in cl:
            rename_map[c] = "yoy_change"
    df = df.rename(columns=rename_map)

    required = ["keyword", "avg_monthly_searches"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"{path.name} missing columns: {missing}. Columns found: {df.columns.tolist()}")

    # Clean up volume column — Keyword Planner uses comma thousands separators
    df["avg_monthly_searches"] = (
        df["avg_monthly_searches"].astype(str)
        .str.replace(",", "", regex=False)
        .str.replace('"', "", regex=False)
        .str.strip()
    )
    df["avg_monthly_searches"] = pd.to_numeric(df["avg_monthly_searches"], errors="coerce").fillna(0)
    df["keyword"] = df["keyword"].astype(str).str.lower().str.strip()

    # Date = first day of the month parsed from filename
    m = CSV_NAME_RE.match(path.name)
    if not m:
        raise RuntimeError(f"Bad filename {path.name}. Expected format YYYY-MM.csv")
    year, month = int(m.group(1)), int(m.group(2))
    df["date"] = pd.Timestamp(year=year, month=month, day=1)

    keep = ["date", "keyword", "avg_monthly_searches"]
    if "three_month_change" in df.columns:
        keep.append("three_month_change")
    if "yoy_change" in df.columns:
        keep.append("yoy_change")
    return df[keep]


def ingest_all_csvs() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("*.csv"))
    files = [f for f in files if CSV_NAME_RE.match(f.name)]
    if not files:
        raise RuntimeError(f"No YYYY-MM.csv files found in {DATA_DIR}")

    log.info(f"Found {len(files)} monthly export(s): {[f.name for f in files]}")
    frames = [parse_keyword_planner_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["date", "keyword"], keep="last")
    log.info(f"Combined: {len(df)} rows, {df['keyword'].nunique()} unique keywords, {df['date'].nunique()} months")
    return df


def tag_keywords(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    kw_to_category = {}
    for category, payload in config["categories"].items():
        for kw in payload["keywords"]:
            kw_to_category[kw.lower()] = category
    kw_to_competitor = {v.lower(): k for k, v in config["competitors"].items()}

    df["category"] = df["keyword"].map(kw_to_category).fillna("uncategorized")
    df["competitor"] = df["keyword"].map(kw_to_competitor)

    unmatched = df[df["category"] == "uncategorized"]["keyword"].unique()
    if len(unmatched):
        log.warning(f"{len(unmatched)} keywords in CSV not in config (will be ignored): {list(unmatched)[:10]}")
    return df


def calculate_sos(df: pd.DataFrame) -> pd.DataFrame:
    """SoS per competitor per month, restricted to branded keywords."""
    branded = df[df["category"] == "branded"].copy()
    monthly = branded.groupby(["date", "competitor"], as_index=False)["avg_monthly_searches"].sum()
    monthly = monthly.rename(columns={"avg_monthly_searches": "search_volume"})
    monthly["total_category"] = monthly.groupby("date")["search_volume"].transform("sum")
    monthly["sos_pct"] = (monthly["search_volume"] / monthly["total_category"] * 100).round(2)
    return monthly.sort_values(["date", "sos_pct"], ascending=[True, False])


def calculate_deltas(sos: pd.DataFrame) -> pd.DataFrame:
    """MoM (month-over-month) and YoY change in SoS points."""
    sos = sos.sort_values(["competitor", "date"]).reset_index(drop=True)
    sos["sos_mom_delta"] = sos.groupby("competitor")["sos_pct"].diff(1).round(2)

    sos["date_yoy_target"] = sos["date"] - pd.DateOffset(years=1)
    yoy_lookup = sos.set_index(["competitor", "date"])["sos_pct"]
    sos["sos_yoy_value"] = sos.apply(
        lambda r: yoy_lookup.get((r["competitor"], r["date_yoy_target"])), axis=1
    )
    sos["sos_yoy_delta"] = (sos["sos_pct"] - sos["sos_yoy_value"]).round(2)
    return sos.drop(columns=["date_yoy_target", "sos_yoy_value"])


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Total volume per category per month — shows where demand sits."""
    summary = df.groupby(["date", "category"], as_index=False)["avg_monthly_searches"].sum()
    return summary.sort_values(["date", "avg_monthly_searches"], ascending=[True, False])


def trade_opportunity(df: pd.DataFrame) -> pd.DataFrame:
    """Latest-month volume for trade-specific keywords — BRUNT's wedge opportunity."""
    latest = df["date"].max()
    trade = df[(df["date"] == latest) & (df["category"] == "trade_specific")]
    return trade[["keyword", "avg_monthly_searches"]].sort_values(
        "avg_monthly_searches", ascending=False
    )


def main():
    log.info("=" * 60)
    log.info("Share of Search pipeline (Keyword Planner mode)")
    log.info("=" * 60)

    ARTIFACTS.mkdir(exist_ok=True)
    config = load_config()

    raw = ingest_all_csvs()
    tagged = tag_keywords(raw, config)
    sos = calculate_sos(tagged)
    sos = calculate_deltas(sos)
    cat_summary = category_summary(tagged)
    trade = trade_opportunity(tagged)

    # Persist artifacts (these are what the dashboard reads)
    tagged.to_csv(ARTIFACTS / "all_keywords_tagged.csv", index=False)
    sos.to_csv(ARTIFACTS / "sos_history.csv", index=False)
    cat_summary.to_csv(ARTIFACTS / "category_summary.csv", index=False)
    trade.to_csv(ARTIFACTS / "trade_opportunity.csv", index=False)

    log.info(f"Wrote artifacts to {ARTIFACTS}")
    latest = sos["date"].max()
    log.info(f"Latest month: {latest.strftime('%Y-%m')}")
    log.info("\nLatest SoS rankings:")
    for _, r in sos[sos["date"] == latest].iterrows():
        delta = f"{r['sos_mom_delta']:+.2f}" if pd.notna(r['sos_mom_delta']) else "n/a"
        log.info(f"  {r['competitor']:<18} {r['sos_pct']:>6.2f}%  MoM: {delta}")


if __name__ == "__main__":
    main()
