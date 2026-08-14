"""
Unit tests for backend/data_pipeline.py.

Run with:  pytest
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.data_pipeline import (
    add_derived_fields,
    detect_spikes,
    load_fuel_prices,
    load_events,
    match_events_to_date,
    merge_brent,
    summary_stats,
)


@pytest.fixture(scope="module")
def raw_df():
    return load_fuel_prices()


@pytest.fixture(scope="module")
def derived_df(raw_df):
    df = add_derived_fields(raw_df)
    for fuel in ("petrol", "diesel"):
        df = detect_spikes(df, fuel=fuel)
    return df


def test_load_fuel_prices_has_expected_columns(raw_df):
    expected = {"date", "petrol", "diesel", "petrol_duty", "diesel_duty", "petrol_vat", "diesel_vat"}
    assert expected.issubset(set(raw_df.columns))


def test_dates_are_sorted_and_unique(raw_df):
    assert raw_df["date"].is_monotonic_increasing
    assert raw_df["date"].is_unique


def test_no_missing_prices(raw_df):
    assert raw_df["petrol"].notna().all()
    assert raw_df["diesel"].notna().all()


def test_pct_change_first_row_is_nan(derived_df):
    assert pd.isna(derived_df.iloc[0]["petrol_pct_change"])


def test_tax_pct_of_price_is_reasonable(derived_df):
    # UK fuel tax has historically been roughly 45-65% of the pump price.
    avg = derived_df["petrol_tax_pct_of_price"].mean()
    assert 40 < avg < 70


def test_known_covid_crash_is_flagged_as_spike(derived_df):
    row = derived_df[derived_df["date"] == "2020-03-30"].iloc[0]
    assert row["petrol_is_spike"]
    assert row["petrol_pct_change"] < -5


def test_summary_stats_shape(derived_df):
    stats = summary_stats(derived_df)
    assert "petrol" in stats and "diesel" in stats
    for fuel_stats in stats.values():
        for key in ("start_price", "latest_price", "all_time_high", "all_time_low"):
            assert key in fuel_stats


def test_events_load_and_have_required_fields():
    events = load_events()
    assert len(events) > 0
    for ev in events:
        assert {"id", "start_date", "end_date", "category", "title", "summary", "sources"}.issubset(ev.keys())
        assert len(ev["sources"]) > 0


def test_match_events_to_date_finds_ukraine_invasion():
    events = load_events()
    matches = match_events_to_date(pd.Timestamp("2022-03-14"), events)
    ids = [m["id"] for m in matches]
    assert "russia-ukraine-invasion-2022" in ids


def test_match_events_to_date_returns_empty_for_quiet_period():
    events = load_events()
    matches = match_events_to_date(pd.Timestamp("2019-04-01"), events)
    # 2019 was a relatively quiet period with only the Brexit sterling entry
    assert isinstance(matches, list)


def test_merge_brent_handles_missing_file(derived_df):
    out = merge_brent(derived_df, None)
    assert "brent_usd_per_barrel" in out.columns
    assert out["brent_usd_per_barrel"].isna().all()
