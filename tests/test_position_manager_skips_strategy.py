import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import paper_position_manager_engine as M

MOD = "app.services.paper_position_manager_engine"


def _run_with(trades, tmp_path):
    fake_ledger = MagicMock()
    fake_ledger.history.return_value = {"trades": trades}
    with patch(f"{MOD}.PaperTradeLedgerEngine", return_value=fake_ledger), \
         patch(f"{MOD}.MarketHoursEngine") as MockHours:
        MockHours.return_value.status.return_value = {
            "is_regular_session": True, "state": "MARKET_OPEN_REGULAR_SESSION"}
        eng = M.PaperPositionManagerEngine()
        eng.ledger_file = tmp_path / "ledger.jsonl"
        out = eng.manage_open_positions()
        written = [json.loads(l) for l in eng.ledger_file.read_text().splitlines() if l.strip()]
    return out, written


def test_momentum_reversal_position_is_never_managed(tmp_path):
    # A MOMENTUM_REVERSAL short that would trip a stop-loss must NOT be closed here —
    # its exits belong to the 5-day rebalance, not this TP/SL manager.
    trade = {
        "status": "OPEN", "symbol": "MSTR", "side": "SELL", "quantity": 10,
        "entry_price": 99.0, "directional_bias": "BEARISH",
        "trade_intent": "MOMENTUM_REVERSAL",
    }
    out, written = _run_with([trade], tmp_path)

    assert out["positions_closed"] == 0
    assert len(written) == 1
    assert written[0]["status"] == "OPEN"
    # left untouched — the manager never even marked it
    assert "manager_status" not in written[0]


def test_non_strategy_position_still_reaches_the_manager(tmp_path):
    # A normal trade is still processed (it gets a manager stamp), proving the skip is
    # specific to the strategy's positions, not a blanket bypass.
    trade = {
        "status": "OPEN", "symbol": "AAPL", "side": "BUY", "quantity": 1,
        "entry_price": 150.0, "directional_bias": "BULLISH", "trade_intent": "BUY",
    }
    out, written = _run_with([trade], tmp_path)

    # It reaches the manager (price unavailable in test -> blocked/stamped), but the key
    # point is it was NOT skipped like the strategy trade.
    assert written[0].get("manager_status") is not None
