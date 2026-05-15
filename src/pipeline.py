"""
Share of Search pipeline - Keyword Planner CSV ingestion.

Reads Keyword Planner CSV exports from data/, unpivots the 12 monthly
"Searches: <Mon> <Year>" columns into long format, builds a unified
history, computes SoS metrics, and writes artifacts for the dashboard.

CSV naming convention: data/YYYY-MM.csv where YYYY-MM is the LATEST month
contained in the file (e.g., data/2026-03.csv covers Apr 2025 - Mar 2026).
When multiple CSVs overlap, the newer file (by filename) wins per
(keyword, date).
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
MONTHLY_COL_RE = re.compile(
    r"^\s*Searches:\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\s*$",
    re.IGNORECASE,
)
MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _read_raw(path: Path) -> pd.DataFrame:
    """Read Keyword Planner CSV across known encodings/delimiters."""
    attempts = [
        ("utf-16", "\t"), ("utf-8", "\t"), ("utf-8-sig", "\t"),
        ("utf-16", ","), ("utf-8", ","), ("utf-8-sig", ","),
    ]
    for enc, sep in attempts:
        try:
            df = pd.read_csv(path, sep=sep, encoding=enc, skiprows=2)
            if "Keyword" in df.columns:
                return df
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue
    raise RuntimeError(f"Could not parse {path.name}. Expected 'Keyword' column.")


def _parse_volume(series: pd.Series) -> pd.Series:
    """Strip commas/quotes from Keyword Planner volumes and coerce to numeric."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace('"', "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def parse_keyword_planner_csv(path: Path) -> pd.DataFrame:
    """
    Unpivot the 12 monthly "Searches: <Mon> <Year>" columns into long format.
    Returns a DataFrame with columns (keyword, date, search_volume).
    """
    df = _read_raw(path)

    # Locate keyword + monthly columns
    kw_col = next((c for c in df.columns if c.lower().strip() == "keyword"), None)
    if kw_col is None:
        raise RuntimeError(f"{path.name}: missing 'Keyword' column.")

    month_cols = {}  # original_col_name -> Timestamp(first-of-month)
    for c in df.columns:
        m = MONTHLY_COL_RE.match(str(c))
        if m:
            mon = MONTH_ABBR[m.group(1).lower()]
            year = int(m.group(2))
            month_cols[c] = pd.Timestamp(year=year, month=mon, day=1)

    if not month_cols:
        raise RuntimeError(
            f"{path.name}: no monthly 'Searches: <Mon> <Year>' columns found. "
            f"Re-export from Keyword Planner with monthly breakdown enabled. "
            f"Columns found: {df.columns.tolist()}"
        )

    if len(month_cols) != 12:
        log.warning(
            f"{path.name}: expected 12 monthly columns, found {len(month_cols)}: "
            f"{sorted(month_cols.values())}"
        )

    df[kw_col] = df[kw_col].astype(str).str.lower().str.strip()
    # Drop the metadata rows at the top (no keyword value)
    df = df[df[kw_col].notna() & (df[kw_col] != "") & (df[kw_col] != "nan")]

    long = df[[kw_col] + list(month_cols.keys())].melt(
        id_vars=[kw_col], var_name="_month_col", value_name="search_volume"
    )
    long = long.rename(columns={kw_col: "keyword"})
    long["date"] = long["_month_col"].map(month_cols)
    long["search_volume"] = _parse_volume(long["search_volume"])
    long = long.drop(columns=["_month_col"])

    # Track filename recency so cross-file dedupe can prefer the newer export
    fname_match = CSV_NAME_RE.match(path.name)
    if not fname_match:
        raise RuntimeError(f"Bad filename {path.name}. Expected format YYYY-MM.csv")
    fyear, fmonth = int(fname_match.group(1)), int(fname_match.group(2))
    long["_source_rank"] = fyear * 100 + fmonth

    return long[["date", "keyword", "search_volume", "_source_rank"]]


def ingest_all_csvs() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("*.csv"))
    files = [f for f in files if CSV_NAME_RE.match(f.name)]
    if not files:
        raise RuntimeError(f"No YYYY-MM.csv files found in {DATA_DIR}")

    log.info(f"Found {len(files)} monthly export(s): {[f.name for f in files]}")
    frames = [parse_keyword_planner_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)

    # When CSVs overlap, keep the row from the most recently named file.
    df = df.sort_values(["keyword", "date", "_source_rank"])
    df = df.drop_duplicates(subset=["keyword", "date"], keep="last")
    df = df.drop(columns=["_source_rank"]).reset_index(drop=True)

    log.info(
        f"Combined: {len(df)} rows, {df['keyword'].nunique()} unique keywords, "
        f"{df['date'].nunique()} months "
        f"({df['date'].min().strftime('%Y-%m')} → {df['date'].max().strftime('%Y-%m')})"
    )
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
    monthly = branded.groupby(["date", "competitor"], as_index=False)["search_volume"].sum()
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
    summary = df.groupby(["date", "category"], as_index=False)["search_volume"].sum()
    return summary.sort_values(["date", "search_volume"], ascending=[True, False])


def trade_opportunity(df: pd.DataFrame) -> pd.DataFrame:
    """Latest-month volume for trade-specific keywords — BRUNT's wedge opportunity."""
    latest = df["date"].max()
    trade = df[(df["date"] == latest) & (df["category"] == "trade_specific")]
    return trade[["keyword", "search_volume"]].sort_values(
        "search_volume", ascending=False
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
