"""VRP study integrity: look-ahead guard (forward window must be complete) and the dual-source
realized-vol cross-check (UW vs TradeStation) that keeps the finding from being one vendor's
artifact."""

import json
from app.services.vrp_research_engine import VRPResearchEngine


def test_series_drops_incomplete_forward_windows(tmp_path, monkeypatch):
    e = VRPResearchEngine()
    e.CACHE = tmp_path
    # one completed window (urv in the past) + one not-yet-complete (urv in the future vs asof)
    (tmp_path / "ZZ.json").write_text(json.dumps([
        {"date": "2025-01-01", "implied_volatility": "0.30", "realized_volatility": "0.25",
         "unshifted_rv_date": "2025-01-31"},
        {"date": "2026-07-01", "implied_volatility": "0.30", "realized_volatility": "0.25",
         "unshifted_rv_date": "2026-08-01"},   # forward window ends AFTER asof -> look-ahead
    ]))
    s = e._series("ZZ", asof="2026-07-15")
    dates = [r[0] for r in s]
    assert "2025-01-01" in dates
    assert "2026-07-01" not in dates, "included a row whose forward realized window hasn't closed"


def test_ts_forward_rv_matches_a_hand_computed_value(tmp_path, monkeypatch):
    """The TS second source must compute forward realized vol over [date, unshifted_rv_date]."""
    import math, statistics
    e = VRPResearchEngine()
    e.CACHE = tmp_path
    (tmp_path / "ZZ.json").write_text(json.dumps([
        {"date": "2026-01-02", "implied_volatility": "0.30", "realized_volatility": "0.25",
         "unshifted_rv_date": "2026-01-08"},
    ]))
    # a tiny TS price series spanning the window
    prices = {"2026-01-02": 100.0, "2026-01-05": 101.0, "2026-01-06": 100.5,
              "2026-01-07": 102.0, "2026-01-08": 101.5}
    monkeypatch.setattr(e, "_ts_closes", lambda t: prices)
    out = e._ts_forward_rv("ZZ", asof="2026-07-15")
    ds = sorted(prices)
    rets = [math.log(prices[ds[i+1]]/prices[ds[i]]) for i in range(len(ds)-1)]
    expected = statistics.pstdev(rets) * math.sqrt(252)
    assert abs(out["2026-01-02"] - expected) < 1e-9


def test_study_reports_both_sources(tmp_path, monkeypatch):
    """A completed study must carry the dual-source cross-check (UW vs TradeStation realized),
    not a single-vendor number. Hermetic: synthetic UW cache + TS bars, no real files."""
    import csv as _csv
    from datetime import date, timedelta

    cache = tmp_path / "uw"; cache.mkdir()
    tr = tmp_path / "tr"; tr.mkdir()

    # deterministic business-day calendar and a smooth price path (no RNG)
    d0 = date(2026, 1, 5)
    days = []
    d = d0
    while len(days) < 160:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    prices = {dd: 100.0 + 8.0 * ((i % 20) - 10) / 10.0 for i, dd in enumerate(days)}  # gentle zigzag

    names = [f"SYN{i:02d}" for i in range(12)]
    for n in names:
        rows = []
        for i in range(0, 120):                 # 120 iv-dates, each forward window +21 bdays
            dt = days[i]; urv = days[i + 21]
            rows.append({"date": dt, "price": prices[dt], "unshifted_rv_date": urv,
                         "implied_volatility": "0.30",        # implied fixed
                         "realized_volatility": "0.24"})       # < implied -> positive VRP
        (cache / f"{n}.json").write_text(json.dumps(rows))
        with open(tr / f"{n}_total_return.csv", "w", newline="") as f:
            w = _csv.writer(f); w.writerow(["date", "close", "adj_close"])
            for dd in days:
                w.writerow([dd, prices[dd], prices[dd]])

    e = VRPResearchEngine()
    e.CACHE = cache
    e._TR = tr
    monkeypatch.setattr(VRPResearchEngine, "_TR", tr)
    r = e.run(names=names, save=False)

    assert r["status"] == "VRP_STUDY_COMPLETE"
    x = r["dual_source_cross_check"]
    assert "TradeStation" in x["realized_vol_sources"]
    assert x["paired_observations"] > 0
    assert x["mean_vrp_uw_realized"] is not None
    assert x["mean_vrp_ts_realized"] is not None       # the independent TS-realized VRP is present
