"""
fetch_brent.py

Pulls the weekly Brent crude spot price (USD/barrel) from FRED
(series WCOILBRENTEU, sourced from the US EIA) so the dashboard can
compare UK pump prices against the underlying global crude benchmark.

FRED publishes this series as an open CSV that does not require an
API key:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=WCOILBRENTEU

If the request fails (e.g. no network access, or FRED is unreachable
from your environment), this script leaves any existing cached CSV in
data/raw/brent_crude_weekly.csv untouched and exits with a clear
message, so the rest of the app can still run on pump-price data alone.

Run manually:
    python backend/fetch_brent.py

Or import fetch_and_cache() from app.py to refresh on demand.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_CSV = BASE_DIR / "data" / "raw" / "brent_crude_weekly.csv"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WCOILBRENTEU"


def fetch_and_cache(url: str = FRED_CSV_URL, out_path: Path = OUT_CSV) -> bool:
    """Download the FRED CSV and save a cleaned copy. Returns True on success."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "fuel-price-analytics/1.0"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[fetch_brent] could not reach FRED ({exc}). Keeping existing cache if present.")
        return False

    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    df.columns = ["date", "brent_usd_per_barrel"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["brent_usd_per_barrel"] = pd.to_numeric(df["brent_usd_per_barrel"], errors="coerce")
    df = df.dropna().sort_values("date")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[fetch_brent] saved {len(df)} weekly Brent observations to {out_path}")
    return True


if __name__ == "__main__":
    ok = fetch_and_cache()
    sys.exit(0 if ok else 1)
