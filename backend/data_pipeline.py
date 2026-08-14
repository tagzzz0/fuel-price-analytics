"""
data_pipeline.py

Cleans the raw gov.uk weekly UK road fuel prices CSV and derives the
analytical fields the frontend needs: percentage changes, rolling
averages, tax burden, and automatically detected price "spikes"
(the biggest weekly moves), which are then cross-referenced against
data/events.json.

Design notes for reviewers:
- All transformations are pure functions of the input DataFrame so this
  module is easy to unit test (see tests/test_data_pipeline.py).
- Spike detection uses a z-score threshold on weekly % change rather
  than a fixed pence threshold, so it stays meaningful whether prices
  are around 120p or 190p.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = BASE_DIR / "data" / "raw" / "uk_fuel_prices_2018_2026.csv"
BRENT_CSV = BASE_DIR / "data" / "raw" / "brent_crude_monthly.csv"
EVENTS_JSON = BASE_DIR / "data" / "events.json"
PROCESSED_CSV = BASE_DIR / "data" / "processed" / "fuel_prices_clean.csv"

SPIKE_Z_THRESHOLD = 1.75  # weekly % change more than this many std devs from mean


def load_fuel_prices(path: Path = RAW_CSV) -> pd.DataFrame:
    """Load and clean the raw gov.uk fuel prices CSV."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [
        "date",
        "petrol",
        "diesel",
        "petrol_duty",
        "diesel_duty",
        "petrol_vat",
        "diesel_vat",
    ]
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y")
    df = df.sort_values("date").reset_index(drop=True)

    numeric_cols = [c for c in df.columns if c != "date"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["petrol", "diesel"]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"[data_pipeline] dropped {dropped} rows with missing price data")

    return df


def load_brent(path: Path = BRENT_CSV) -> Optional[pd.DataFrame]:
    """Load the monthly Brent crude series (FRED MCOILBRENTEU), if present."""
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def merge_brent(df: pd.DataFrame, brent: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Attach the nearest-prior-month Brent price to each weekly fuel row.

    Brent is published monthly and fuel prices weekly, so a straight join
    would leave most weeks empty. merge_asof carries the latest known
    monthly Brent reading forward to every week until the next month's
    reading arrives - a standard, defensible way to compare series of
    different frequencies without inventing data.
    """
    df = df.copy()
    if brent is None:
        df["brent_usd_per_barrel"] = pd.NA
        return df
    df = pd.merge_asof(df.sort_values("date"), brent.sort_values("date"), on="date", direction="backward")
    return df



def add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add % changes, rolling averages and tax burden columns."""
    df = df.copy()

    for fuel in ("petrol", "diesel"):
        df[f"{fuel}_pct_change"] = df[fuel].pct_change() * 100
        df[f"{fuel}_4wk_avg"] = df[fuel].rolling(4, min_periods=1).mean()
        df[f"{fuel}_52wk_avg"] = df[fuel].rolling(52, min_periods=1).mean()

        duty_col = f"{fuel}_duty"
        vat_col = f"{fuel}_vat"
        # VAT is charged on (product + duty), so the cash VAT amount:
        df[f"{fuel}_vat_amount"] = df[fuel] - (df[fuel] / (1 + df[vat_col] / 100))
        df[f"{fuel}_tax_total"] = df[duty_col] + df[f"{fuel}_vat_amount"]
        df[f"{fuel}_tax_pct_of_price"] = (df[f"{fuel}_tax_total"] / df[fuel]) * 100

    df["year"] = df["date"].dt.year
    return df


def detect_spikes(df: pd.DataFrame, fuel: str = "petrol", z_threshold: float = SPIKE_Z_THRESHOLD) -> pd.DataFrame:
    """Flag weeks whose % change is a statistical outlier vs the whole series."""
    col = f"{fuel}_pct_change"
    mean = df[col].mean()
    std = df[col].std()
    df = df.copy()
    df[f"{fuel}_zscore"] = (df[col] - mean) / std
    df[f"{fuel}_is_spike"] = df[f"{fuel}_zscore"].abs() >= z_threshold
    return df


def load_events(path: Path = EVENTS_JSON) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def match_events_to_date(date: pd.Timestamp, events: list[dict]) -> list[dict]:
    """Return events whose [start_date, end_date] window contains `date`."""
    matches = []
    for ev in events:
        start = pd.Timestamp(ev["start_date"])
        end = pd.Timestamp(ev["end_date"])
        if start <= date <= end:
            matches.append(ev)
    return matches


def build_spike_report(df: pd.DataFrame, events: list[dict], fuel: str = "petrol", top_n: int = 20) -> list[dict]:
    """Rank the biggest weekly moves and attach any matching researched events."""
    spikes = df[df[f"{fuel}_is_spike"]].copy()
    spikes = spikes.reindex(spikes[f"{fuel}_pct_change"].abs().sort_values(ascending=False).index)
    spikes = spikes.head(top_n)

    report = []
    for _, row in spikes.iterrows():
        matched = match_events_to_date(row["date"], events)
        report.append(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "price": round(float(row[fuel]), 2),
                "pct_change": round(float(row[f"{fuel}_pct_change"]), 2),
                "direction": "rise" if row[f"{fuel}_pct_change"] > 0 else "fall",
                "events": [{"id": e["id"], "title": e["title"], "category": e["category"]} for e in matched],
            }
        )
    return report


def summary_stats(df: pd.DataFrame) -> dict:
    """High-level numbers for the dashboard header / bottom summary text."""
    stats = {}
    for fuel in ("petrol", "diesel"):
        first = df.iloc[0]
        last = df.iloc[-1]
        max_row = df.loc[df[fuel].idxmax()]
        min_row = df.loc[df[fuel].idxmin()]
        stats[fuel] = {
            "start_price": round(float(first[fuel]), 2),
            "start_date": first["date"].strftime("%Y-%m-%d"),
            "latest_price": round(float(last[fuel]), 2),
            "latest_date": last["date"].strftime("%Y-%m-%d"),
            "change_since_start_pct": round(float((last[fuel] - first[fuel]) / first[fuel] * 100), 1),
            "all_time_high": round(float(max_row[fuel]), 2),
            "all_time_high_date": max_row["date"].strftime("%Y-%m-%d"),
            "all_time_low": round(float(min_row[fuel]), 2),
            "all_time_low_date": min_row["date"].strftime("%Y-%m-%d"),
            "avg_tax_pct_of_price": round(float(df[f"{fuel}_tax_pct_of_price"].mean()), 1),
        }
    return stats


def run_pipeline(save: bool = True) -> pd.DataFrame:
    df = load_fuel_prices()
    df = add_derived_fields(df)
    for fuel in ("petrol", "diesel"):
        df = detect_spikes(df, fuel=fuel)

    brent = load_brent()
    df = merge_brent(df, brent)

    if save:
        PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(PROCESSED_CSV, index=False)
        print(f"[data_pipeline] wrote {len(df)} rows to {PROCESSED_CSV}")

    return df


if __name__ == "__main__":
    run_pipeline()
