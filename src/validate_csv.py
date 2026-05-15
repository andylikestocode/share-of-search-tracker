"""
Validate a Keyword Planner CSV before committing.

Usage:
    python src/validate_csv.py ~/Downloads/Keyword_Stats_2026-05.csv
    python src/validate_csv.py data/2026-05.csv

Checks:
  1. File can be read (encoding + delimiter)
  2. Required columns exist
  3. Volume column parses as numbers (not bucketed ranges like "1K - 10K")
  4. Filename follows YYYY-MM.csv convention (warns if not)
  5. Keyword coverage vs config/keywords.yaml — flags missing + extras
  6. Suggests the correct destination path

Exits 0 if green, 1 if errors. Run as:
    python src/validate_csv.py path/to/file.csv && cp path/to/file.csv data/YYYY-MM.csv
"""
import re
import sys
import shutil
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "keywords.yaml"
DATA_DIR = ROOT / "data"
CSV_NAME_RE = re.compile(r"^(\d{4})-(\d{2})\.csv$")
MONTHLY_COL_RE = re.compile(
    r"^\s*Searches:\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\s*$",
    re.IGNORECASE,
)

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg):
    print(f"{GREEN}✓{RESET} {msg}")


def warn(msg):
    print(f"{YELLOW}⚠{RESET}  {msg}")


def err(msg):
    print(f"{RED}✗{RESET} {msg}")


def info(msg):
    print(f"{BLUE}ℹ{RESET}  {msg}")


def header(msg):
    print(f"\n{BOLD}{msg}{RESET}")


def try_read(path: Path):
    """Returns (df, encoding_used, sep_used) or (None, None, None)."""
    attempts = [
        ("utf-16", "\t"),
        ("utf-8", "\t"),
        ("utf-8-sig", "\t"),
        ("utf-16", ","),
        ("utf-8", ","),
        ("utf-8-sig", ","),
    ]
    for enc, sep in attempts:
        try:
            df = pd.read_csv(path, sep=sep, encoding=enc, skiprows=2)
            if "Keyword" in df.columns or "keyword" in df.columns:
                return df, enc, sep
        except Exception:
            continue
    return None, None, None


def find_volume_column(df: pd.DataFrame):
    for c in df.columns:
        cl = c.lower().strip()
        if "avg" in cl and "search" in cl:
            return c
    return None


def find_monthly_columns(df: pd.DataFrame):
    """Returns list of (column_name, year, month) for "Searches: <Mon> <Year>" columns."""
    found = []
    for c in df.columns:
        m = MONTHLY_COL_RE.match(str(c))
        if m:
            found.append((c, int(m.group(2)), m.group(1).title()))
    return found


def find_keyword_column(df: pd.DataFrame):
    for c in df.columns:
        if c.lower().strip() == "keyword":
            return c
    return None


def detect_bucketed_volumes(series: pd.Series) -> int:
    """Count rows where volume looks like a range ('1K - 10K') rather than a number."""
    bucket_patterns = [
        re.compile(r"^\s*\d+[KMB]?\s*[-–]\s*\d+[KMB]?\s*$", re.IGNORECASE),
        re.compile(r"^\s*<\s*\d+", re.IGNORECASE),
    ]
    count = 0
    for v in series:
        s = str(v) if v is not None else ""
        for pat in bucket_patterns:
            if pat.match(s):
                count += 1
                break
    return count


def validate(path: Path) -> bool:
    """Returns True if file is valid for the pipeline."""
    header(f"Validating: {path}")

    if not path.exists():
        err(f"File does not exist: {path}")
        return False
    ok(f"File exists ({path.stat().st_size:,} bytes)")

    # 1. Filename check
    if CSV_NAME_RE.match(path.name):
        ok(f"Filename matches YYYY-MM.csv convention")
        target = DATA_DIR / path.name
    else:
        warn(f"Filename '{path.name}' is not in YYYY-MM.csv format")
        info("  Suggestion: rename it before committing, e.g. data/2026-05.csv")
        target = None

    # 2. Parse attempt
    df, enc, sep = try_read(path)
    if df is None:
        err("Could not parse this file as a Keyword Planner export.")
        info("  Make sure you exported as 'CSV (.csv)' from Keyword Planner")
        info("  (not Google Sheets, not Excel)")
        return False
    sep_label = "tab" if sep == "\t" else "comma"
    ok(f"Parsed successfully (encoding: {enc}, delimiter: {sep_label}, rows: {len(df)})")

    # 3. Required columns
    kw_col = find_keyword_column(df)
    if not kw_col:
        err(f"Missing 'Keyword' column. Found columns: {df.columns.tolist()}")
        return False
    ok(f"Found keyword column: '{kw_col}'")

    monthly_cols = find_monthly_columns(df)
    if not monthly_cols:
        err("Missing the 12 monthly 'Searches: <Mon> <Year>' columns.")
        info("  Your export looks like an aggregate-only report — the pipeline now needs the")
        info("  monthly breakdown to backfill 12 months of history per CSV.")
        info("  In Keyword Planner: open your saved plan → 'Historical metrics' tab →")
        info("  use the column chooser to enable 'Searches: <Month>' for the last 12 months,")
        info("  then export.")
        info(f"  Found columns: {df.columns.tolist()}")
        return False
    ok(f"Found {len(monthly_cols)} monthly Searches columns")
    if len(monthly_cols) != 12:
        warn(f"Expected 12 monthly columns, found {len(monthly_cols)}: "
             f"{[f'{m} {y}' for _, y, m in monthly_cols]}")
        info("  Pipeline will still ingest, but history will be partial.")

    vol_col = find_volume_column(df)
    if vol_col:
        ok(f"Found aggregate volume column: '{vol_col}' (informational only — pipeline uses monthly)")

    # 4. Volume format check (bucketed vs precise) — sample the monthly columns
    total_rows = len(df)
    bucket_count = 0
    for c, _, _ in monthly_cols:
        bucket_count += detect_bucketed_volumes(df[c])
    if bucket_count > 0:
        total_cells = total_rows * len(monthly_cols)
        bucket_pct = bucket_count / total_cells * 100
        if bucket_pct > 50:
            err(f"{bucket_count}/{total_cells} cells ({bucket_pct:.0f}%) across monthly "
                f"columns have BUCKETED volumes (e.g. '1K - 10K'), not precise numbers.")
            info("  This means the Google Ads account doesn't have enough spend for exact data.")
            info("  Try exporting from a higher-spend BRUNT Google Ads account.")
            return False
        else:
            warn(f"{bucket_count}/{total_cells} cells ({bucket_pct:.0f}%) have bucketed volumes.")
            info("  Pipeline will treat these as 0. Higher-spend account would give exact numbers.")
    else:
        ok("All monthly volumes are precise numbers (not bucketed)")

    # 5. Keyword coverage check vs config
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    expected = set()
    for cat in config["categories"].values():
        for kw in cat["keywords"]:
            expected.add(kw.lower())

    found = set(df[kw_col].astype(str).str.lower().str.strip())

    missing = expected - found
    extras = found - expected

    if missing:
        warn(f"{len(missing)} keywords in config/keywords.yaml NOT in your CSV:")
        for kw in sorted(missing)[:15]:
            print(f"     - {kw}")
        if len(missing) > 15:
            print(f"     ... and {len(missing) - 15} more")
        info("  Pipeline will skip these silently. Add them to your Keyword Planner saved plan to capture.")
    else:
        ok(f"All {len(expected)} configured keywords are present in CSV")

    if extras:
        info(f"{len(extras)} keywords in CSV not in config (will be ignored as 'uncategorized'):")
        for kw in sorted(extras)[:5]:
            print(f"     - {kw}")
        if len(extras) > 5:
            print(f"     ... and {len(extras) - 5} more")

    # 6. Suggest destination
    header("Next steps")
    if target:
        if target.exists():
            warn(f"data/{path.name} already exists — pushing will overwrite it")
        info(f"Move into place:")
        print(f"     mv '{path}' '{target}'")
        info(f"Commit:")
        print(f"     git add data/{path.name}")
        print(f"     git commit -m 'data: {path.stem}'")
        print(f"     git push")
    else:
        # Try to infer YYYY-MM from columns or just suggest the user pick
        info(f"Rename to YYYY-MM.csv first, then drop in data/")

    print()
    print(f"{GREEN}{BOLD}✓ CSV is valid — safe to commit.{RESET}\n")
    return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python src/validate_csv.py path/to/file.csv")
        sys.exit(2)

    path = Path(sys.argv[1]).expanduser().resolve()
    success = validate(path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
