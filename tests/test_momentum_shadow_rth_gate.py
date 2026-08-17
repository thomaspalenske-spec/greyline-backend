"""The shadow may only OPEN or SETTLE a hypothetical cohort when the transaction could ACTUALLY have
been executed on TradeStation at that moment — i.e. during a regular session at a live quote — even
though zero capital is at risk. Regression guard for the 2026-08-17 Sunday-night open at Friday's stale
close (which mislabeled every leg entry_live=True). Zero-capital, read-only: never places an order.
"""

import json

from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine as M


def _targets():
    # a clean LIVE signal so ONLY the market-open gate decides whether a cohort opens
    legs = [{"symbol": "AAA", "side": "BUY", "last_close": 10.0, "conviction": 1.5},
            {"symbol": "BBB", "side": "SELL", "last_close": 20.0, "conviction": 1.4}]
    return (legs, [], "2026-08-17", 2, "TRADESTATION_LIVE")


def _mk(tmp_path, monkeypatch, *, rth):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_EQUITY_SHADOW", "true")
    m = M()
    monkeypatch.setattr(m, "_market_open", lambda: rth)
    monkeypatch.setattr(m, "_signal_targets", lambda prefer_live=True: _targets())
    monkeypatch.setattr(m, "_live_prices", lambda syms: {s.upper(): 11.0 for s in syms})
    monkeypatch.setattr(m, "_report_settled", lambda rec: None)   # no iMessage side-effect in tests
    m.STATE.mkdir(parents=True, exist_ok=True)
    return m


def test_no_open_when_market_closed(tmp_path, monkeypatch):
    m = _mk(tmp_path, monkeypatch, rth=False)
    out = m.mark()
    assert out["cohort_opened"] is False
    assert "market closed" in (out.get("open_skipped") or "")
    assert m.OPEN.read_text().strip() in ("[]", "")     # nothing recorded


def test_opens_when_market_open(tmp_path, monkeypatch):
    m = _mk(tmp_path, monkeypatch, rth=True)
    out = m.mark()
    assert out["cohort_opened"] is True
    cohorts = json.loads(m.OPEN.read_text())
    assert len(cohorts) == 1 and len(cohorts[0]["legs"]) == 2
    # entered at the LIVE quote (11.0), and entry_live is TRUE only because the market was open
    assert all(l["entry_live"] is True and l["entry_close"] == 11.0 for l in cohorts[0]["legs"])


def test_matured_cohort_not_settled_when_market_closed(tmp_path, monkeypatch):
    m = _mk(tmp_path, monkeypatch, rth=False)
    # a cohort whose HOLD_DAYS elapsed long ago — but the market is shut, so it must NOT settle
    m.OPEN.write_text(json.dumps([{
        "opened": "2026-08-01", "opened_at": "2026-08-01T14:00:00", "top_n": 2, "source": "TRADESTATION_LIVE",
        "legs": [{"symbol": "AAA", "side": "BUY", "entry_close": 10.0, "entry_live": True},
                 {"symbol": "BBB", "side": "SELL", "entry_close": 20.0, "entry_live": True}]}]))
    out = m.mark()
    assert out["cohorts_closed"] == 0
    assert len(json.loads(m.OPEN.read_text())) == 1          # still held, awaiting a live-quote settle
    assert not m.CLOSED.exists() or m.CLOSED.read_text().strip() == ""


def test_matured_cohort_settles_when_market_open(tmp_path, monkeypatch):
    m = _mk(tmp_path, monkeypatch, rth=True)
    m.OPEN.write_text(json.dumps([{
        "opened": "2026-08-01", "opened_at": "2026-08-01T14:00:00", "top_n": 2, "source": "TRADESTATION_LIVE",
        "legs": [{"symbol": "AAA", "side": "BUY", "entry_close": 10.0, "entry_live": True},
                 {"symbol": "BBB", "side": "SELL", "entry_close": 20.0, "entry_live": True}]}]))
    out = m.mark()
    assert out["cohorts_closed"] == 1
    assert m.CLOSED.read_text().strip() != ""                 # settled at the live quote
