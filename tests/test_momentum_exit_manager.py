import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.trade_doctrine_engine import TradeDoctrineEngine
from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine

NOW = datetime(2026, 7, 20, 15, 0, 0)


def _trade(direction="LONG", entry=100.0, atr=4.0, qty=100.0, opened="2026-07-20T14:00:00"):
    plan = TradeDoctrineEngine().exit_plan(entry, direction, atr)
    return {
        "symbol": "TST", "status": "OPEN", "trade_intent": "MOMENTUM_REVERSAL",
        "side": "BUY" if direction == "LONG" else "SELL",
        "original_quantity": qty, "quantity": qty, "entry_price": entry,
        "exit_doctrine": plan,
        "doctrine_state": {"tps_filled": 0, "extreme": entry,
                           "remaining_quantity": qty, "opened_at": opened},
    }


def test_hold_when_between_stop_and_first_target():
    acts, st = MomentumExitManagerEngine().decide(_trade(), price=103.0, now=NOW)
    assert acts == []
    assert st["remaining_quantity"] == 100.0


def test_first_target_scales_out_25pct():
    acts, st = MomentumExitManagerEngine().decide(_trade(), price=106.0, now=NOW)
    assert len(acts) == 1 and acts[0]["type"] == "SCALE" and acts[0]["reason"] == "TP1"
    assert acts[0]["qty"] == 25.0
    assert st["tps_filled"] == 1
    assert st["remaining_quantity"] == 75.0
    assert st["current_stop"] == 100.0        # ratcheted to breakeven


def test_gap_through_all_three_targets_leaves_runner():
    acts, st = MomentumExitManagerEngine().decide(_trade(), price=118.0, now=NOW)
    scales = [a for a in acts if a["type"] == "SCALE"]
    assert len(scales) == 3                    # banked TP1/2/3
    assert st["tps_filled"] == 3
    assert st["remaining_quantity"] == 25.0    # the runner rides on
    assert st["current_stop"] == 112.0         # floored at TP2


def test_stop_closes_the_position():
    acts, st = MomentumExitManagerEngine().decide(_trade(), price=89.0, now=NOW)
    assert acts and acts[-1]["type"] == "CLOSE" and acts[-1]["reason"] == "STOP"
    assert st["remaining_quantity"] == 0


def test_max_hold_closes_the_position():
    old = _trade(opened="2026-06-01T14:00:00")   # > 20 days before NOW
    acts, st = MomentumExitManagerEngine().decide(old, price=101.0, now=NOW)
    assert acts and acts[-1]["reason"] == "MAX_HOLD"
    assert st["remaining_quantity"] == 0


def test_manage_open_positions_scales_and_writes(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock
    from app.services import momentum_exit_manager_engine as M

    trade = _trade(entry=100.0, atr=4.0, qty=100.0)
    trade["symbol"] = "TST"
    fake_led = MagicMock()
    fake_led._read_all.return_value = [trade]
    monkeypatch.setattr(M, "PaperTradeLedgerEngine", lambda: fake_led)
    quote = MagicMock()
    quote.get_quote.return_value = {"response_json": {"Quotes": [{"Last": "106.0"}]}}
    monkeypatch.setattr(M, "TradeStationQuoteLiveEngine", lambda: quote)

    eng = M.MomentumExitManagerEngine()
    eng.ledger_file = tmp_path / "ledger.jsonl"
    out = eng.manage_open_positions()

    assert out["scaled_out"] == 1
    written = [json.loads(l) for l in eng.ledger_file.read_text().splitlines() if l.strip()]
    assert written[0]["quantity"] == 75.0                 # 25% banked
    assert written[0]["doctrine_state"]["tps_filled"] == 1
    assert written[0]["realized_pnl"] > 0


def test_short_is_mirrored():
    # short entry 100; price falls to 94 -> TP1 (94) hit, a WIN
    acts, st = MomentumExitManagerEngine().decide(_trade("SHORT"), price=94.0, now=NOW)
    assert acts[0]["type"] == "SCALE" and acts[0]["reason"] == "TP1"
    assert acts[0]["realized"] > 0             # short profits as price falls
    # short stop is above entry
    acts2, _ = MomentumExitManagerEngine().decide(_trade("SHORT"), price=111.0, now=NOW)
    assert acts2[-1]["reason"] == "STOP"
