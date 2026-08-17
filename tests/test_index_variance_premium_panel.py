"""The index variance premium forward panel — the out-of-sample arbiter for the one candidate that
cleared significance. Records the confirmed index harvest set, resolves ~30d out, verdict only when
powered, block-bootstrap CI (autocorrelation-robust)."""

import json
from app.services.index_variance_premium_panel_engine import IndexVariancePremiumPanelEngine
from app.services.conditional_vrp_short_premium_engine import INDEX_ETFS, CROSS_ASSET_ETFS, VARIANCE_HARVEST


def _panel(tmp_path):
    e = IndexVariancePremiumPanelEngine()
    e.PANEL = tmp_path / "ivp.jsonl"
    return e


def test_harvest_set_is_distinct_high_vrp_indices():
    # SPY kept; redundant S&P clones collapsed out; near-zero-VRP names excluded
    assert "SPY" in INDEX_ETFS and "RSP" in INDEX_ETFS
    for redundant in ("VOO", "IVV", "VTI"):
        assert redundant not in INDEX_ETFS, "redundant S&P clone should be collapsed to SPY"
    for zero in ("EEM", "XLV", "AAPL"):
        assert zero not in INDEX_ETFS
    # cross-asset diversifiers (independent tails) are harvested; gold (negative VRP) is NOT
    for div in ("TLT", "HYG", "USO", "UUP"):
        assert div in CROSS_ASSET_ETFS and div in VARIANCE_HARVEST
    for neg in ("GLD", "SLV", "GDX"):
        assert neg not in VARIANCE_HARVEST


def test_records_each_index_etf_once(tmp_path, monkeypatch):
    e = _panel(tmp_path)
    from datetime import date, timedelta
    days, d = [], date(2026, 1, 1)
    while len(days) < 65:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    series = [{"date": dd, "implied_volatility": "0.15", "realized_volatility": "0.12",
               "unshifted_rv_date": "2099-01-01"} for dd in days]
    monkeypatch.setattr(e, "_fresh_series", lambda t: series)
    r = e.record()
    assert r["recorded"] == len(VARIANCE_HARVEST)   # equity + cross-asset
    # idempotent: recording again adds nothing for the same date
    assert e.record()["recorded"] == 0


def test_resolves_completed_window_and_computes_vrp(tmp_path, monkeypatch):
    e = _panel(tmp_path)
    e.PANEL.write_text(json.dumps({"kind": "pending", "ticker": "SPY", "entry_date": "2026-01-05",
                                   "forward_end": "2026-02-04", "entry_iv": 0.16, "iv_rank": 0.7}) + "\n")
    monkeypatch.setattr(e, "_fresh_series", lambda t: [{"date": "2026-01-05", "realized_volatility": "0.13"}])
    monkeypatch.setattr(e.vrp, "_ts_forward_rv", lambda t, asof: {"2026-01-05": 0.135})
    e.resolve()
    row = [json.loads(l) for l in e.PANEL.read_text().splitlines() if '"resolved"' in l][0]
    assert row["vrp"] == round(0.16 - 0.13, 4)          # IV - forward realized (UW preferred)
    assert row["uw_realized"] == 0.13 and row["ts_realized"] == 0.135


def test_no_verdict_until_powered(tmp_path):
    e = _panel(tmp_path)
    e.PANEL.write_text("".join(
        json.dumps({"kind": "resolved", "ticker": "SPY", "entry_date": f"2026-01-{d:02d}",
                    "month": "2026-01", "vrp": 0.02}) + "\n" for d in range(1, 6)))
    s = e.status()
    assert s["verdict"] == "INSUFFICIENT_OUT_OF_SAMPLE_DATA" and s["resolved_out_of_sample"] == 5
