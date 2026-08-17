"""The forward panel earns significance OUT OF SAMPLE: it records rich-IV/non-earnings entries live
and resolves them only after the 30-day window closes, never re-using the backtest year, and offers
no verdict until powered."""

import json
from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine


def _panel(tmp_path):
    e = ConditionalVRPForwardPanelEngine()
    e.PANEL = tmp_path / "panel.jsonl"
    return e


def test_records_only_rich_iv_non_earnings_entries(tmp_path, monkeypatch):
    e = _panel(tmp_path)
    # a fresh series (>=60 rows, the engine's minimum) where the LATEST IV is the highest in its
    # trailing history -> causal rank 1.0 (rich)
    from datetime import date, timedelta
    days, d = [], date(2026, 1, 1)
    while len(days) < 65:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    series = [{"date": dd, "implied_volatility": "0.20", "realized_volatility": "0.18",
               "unshifted_rv_date": "2099-01-01", "price": 100} for dd in days[:-1]]
    series.append({"date": days[-1], "implied_volatility": "0.60",   # today: high IV
                   "realized_volatility": None, "unshifted_rv_date": "2099-03-01", "price": 100})
    monkeypatch.setattr(e, "_fresh_series", lambda t: series)
    monkeypatch.setattr(e.cvrp, "_earnings_dates", lambda t: [])
    r = e.record_signals(names=["ZZ"])
    assert r["recorded"] == 1
    rows = [json.loads(l) for l in e.PANEL.read_text().splitlines()]
    assert rows[0]["kind"] == "pending" and rows[0]["entry_date"] == days[-1]
    assert rows[0]["iv_rank"] == 1.0

    # earnings inside the forward window -> excluded
    e2 = _panel(tmp_path / "b"); (tmp_path / "b").mkdir()
    e2.PANEL = tmp_path / "panel2.jsonl"
    monkeypatch.setattr(e2, "_fresh_series", lambda t: series)
    monkeypatch.setattr(e2.cvrp, "_earnings_dates", lambda t: ["2099-02-15"])
    assert e2.record_signals(names=["ZZ"])["recorded"] == 0


def test_does_not_resolve_before_the_window_closes(tmp_path, monkeypatch):
    e = _panel(tmp_path)
    e.PANEL.write_text(json.dumps({"kind": "pending", "ticker": "ZZ", "entry_date": "2026-06-01",
                                   "forward_end": "2099-01-01", "entry_iv": 0.5, "iv_rank": 0.9}) + "\n")
    monkeypatch.setattr(e, "_fresh_series", lambda t: [])
    monkeypatch.setattr(e.vrp, "_ts_forward_rv", lambda t, asof: {})
    assert e.resolve()["resolved"] == 0            # forward_end far in the future -> not resolved


def test_resolves_completed_window_dual_source(tmp_path, monkeypatch):
    e = _panel(tmp_path)
    e.PANEL.write_text(json.dumps({"kind": "pending", "ticker": "ZZ", "entry_date": "2026-01-05",
                                   "forward_end": "2026-02-04", "entry_iv": 0.40, "iv_rank": 0.9}) + "\n")
    # UW now reports the completed forward realized for that entry date
    monkeypatch.setattr(e, "_fresh_series", lambda t: [
        {"date": "2026-01-05", "realized_volatility": "0.28"}])
    monkeypatch.setattr(e.vrp, "_ts_forward_rv", lambda t, asof: {"2026-01-05": 0.30})
    r = e.resolve()
    assert r["resolved"] == 1
    row = [json.loads(l) for l in e.PANEL.read_text().splitlines() if '"resolved"' in l][0]
    assert row["uw_realized"] == 0.28 and row["ts_realized"] == 0.30      # dual-source captured
    # gross edge = 0.5*(iv-rv)/iv*1e4, positive since 0.40 > 0.28
    assert row["gross_edge_bps"] > 0


def test_no_verdict_until_powered(tmp_path):
    e = _panel(tmp_path)
    e.PANEL.write_text("".join(
        json.dumps({"kind": "resolved", "ticker": "ZZ", "entry_date": f"2026-01-{d:02d}",
                    "month": "2026-01", "gross_edge_bps": 200.0}) + "\n" for d in range(1, 6)))
    s = e.panel_status()
    assert s["verdict"] == "INSUFFICIENT_OUT_OF_SAMPLE_DATA"
    assert s["resolved_out_of_sample"] == 5
