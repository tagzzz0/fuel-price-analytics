"""
app.py - Flask application entry point.

Serves:
  - The frontend (templates/index.html + static assets)
  - A small JSON REST API the frontend's JS consumes:
      GET /api/prices?fuel=petrol&start=YYYY-MM-DD&end=YYYY-MM-DD
          -> weekly pump price, % change, rolling averages, tax split,
             spike flag, AND the nearest-month Brent crude USD/bbl
      GET /api/summary
      GET /api/spikes?fuel=petrol&top=20
      GET /api/events

Run with:  python run.py
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

from backend.data_pipeline import (
    load_events,
    build_spike_report,
    run_pipeline,
    summary_stats,
)


def _clean_records(records: list[dict]) -> list[dict]:
    """Replace NaN/NaT with None so the output is valid JSON (NaN itself is not)."""
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
    return records


BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "frontend" / "templates"),
    static_folder=str(BASE_DIR / "frontend" / "static"),
)

# Data is loaded once at startup and cached in memory - this dataset is
# small (450 rows) so there's no need for a database. We deliberately do
# NOT write the processed CSV here (save=False): writing files as a side
# effect of starting the web server is bad practice, and it also confuses
# Flask's debug-mode file watcher into an infinite reload loop. Run
# `python backend/data_pipeline.py` separately to (re)generate the
# data/processed/fuel_prices_clean.csv artifact.
_df = run_pipeline(save=False)
_events = load_events()


def _filter_by_date(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/prices")
def api_prices():
    fuel = request.args.get("fuel", "petrol")
    if fuel not in ("petrol", "diesel"):
        return jsonify({"error": "fuel must be 'petrol' or 'diesel'"}), 400

    df = _filter_by_date(_df, request.args.get("start"), request.args.get("end"))

    cols = [
        "date", fuel, f"{fuel}_pct_change", f"{fuel}_4wk_avg", f"{fuel}_52wk_avg",
        f"{fuel}_duty", f"{fuel}_vat", f"{fuel}_tax_pct_of_price", f"{fuel}_is_spike",
        "brent_usd_per_barrel",
    ]
    out = df[cols].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.rename(columns={
        fuel: "price",
        f"{fuel}_pct_change": "pct_change",
        f"{fuel}_4wk_avg": "avg_4wk",
        f"{fuel}_52wk_avg": "avg_52wk",
        f"{fuel}_duty": "duty",
        f"{fuel}_vat": "vat_pct",
        f"{fuel}_tax_pct_of_price": "tax_pct_of_price",
        f"{fuel}_is_spike": "is_spike",
    })
    records = _clean_records(out.to_dict(orient="records"))
    return jsonify(records)


@app.route("/api/summary")
def api_summary():
    return jsonify(summary_stats(_df))


@app.route("/api/spikes")
def api_spikes():
    fuel = request.args.get("fuel", "petrol")
    top_n = int(request.args.get("top", 20))
    return jsonify(build_spike_report(_df, _events, fuel=fuel, top_n=top_n))


@app.route("/api/events")
def api_events():
    return jsonify(_events)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
