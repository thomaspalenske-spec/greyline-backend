import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

MOD = "app.services.momentum_reversal_rebalance_engine"


def _confirmed_bullish():
    c = [100.0] * 260
    c[-253] = 90.0     # 12mo-ago low -> bullish momentum
    c[-22] = 100.0
    c[-6] = 101.0      # recent move down -> reversal bullish (agrees)
    c[-1] = 100.0
    return c


def test_blocked_when_execution_disabled(monkeypatch):
    monkeypatch.delenv("GREYLINE_PAPER_EXECUTION_ENABLED", raising=False)
    out = MomentumReversalRebalanceEngine().rebalance(force=True)
    assert out["rebalanced"] is False
    assert "EXECUTION_DISABLED" in out["status"]


def test_skipped_when_not_due(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    eng = MomentumReversalRebalanceEngine()
    eng.STATE = tmp_path / "state.json"
    eng.STATE.write_text('{"last_rebalance_at": "%s"}' % datetime.utcnow().isoformat())
    with patch(f"{MOD}.MarketHoursEngine") as M:
        M.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
        out = eng.rebalance(force=False)   # not forced -> honors the schedule
    assert out["rebalanced"] is False
    assert out["status"] == "REBALANCE_SKIPPED_NOT_DUE"


def _sandbox(tmp_path, monkeypatch, universe):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    eng = MomentumReversalRebalanceEngine(top_n=2)
    eng.STATE = tmp_path / "state.json"
    led = PaperTradeLedgerEngine()
    led.ledger_file = tmp_path / "ledger.jsonl"
    eng.ledger = led
    monkeypatch.setattr(eng.strategy, "universe",
                        lambda prefer_live=True: (universe, "2026-07-15", "TEST"))
    m = patch(f"{MOD}.MarketHoursEngine")
    lim = patch(f"{MOD}.PositionExposureLimitEngine")
    mm, ll = m.start(), lim.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    ll.return_value.evaluate.return_value = {"limits_ok": True}
    monkeypatch.setattr("app.services.momentum_reversal_strategy_engine.PositionExposureLimitEngine",
                        ll)  # keep any strategy-side check consistent
    return eng, led, (m, lim)


def test_rebalance_opens_then_realizes(tmp_path, monkeypatch):
    uni = {"AAA": _confirmed_bullish(), "BBB": _confirmed_bullish()}
    eng, led, patches = _sandbox(tmp_path, monkeypatch, uni)
    try:
        r1 = eng.rebalance(force=True)
        assert r1["rebalanced"] is True
        assert len(r1["opened"]) == 2
        opens = [t for t in led._read_all() if t.get("status") == "OPEN"]
        assert len(opens) == 2
        assert all(t["trade_intent"] == "MOMENTUM_REVERSAL" for t in opens)

        # second rebalance realizes the prior two and re-opens
        r2 = eng.rebalance(force=True)
        assert len(r2["closed"]) == 2
        still_open = [t for t in led._read_all() if t.get("status") == "OPEN"]
        assert len(still_open) == 2   # re-opened fresh
    finally:
        for p in patches:
            p.stop()
