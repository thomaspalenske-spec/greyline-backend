import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_position_manager_engine import PaperPositionManagerEngine

MOD = "app.services.paper_position_manager_engine"


# NOTE: the previous tests here targeted a removed API (get_active_positions /
# close_position / LedgerEngine). The engine now exposes manage_open_positions().


def test_manage_open_positions_no_trades():
    with patch(f"{MOD}.PaperTradeLedgerEngine") as MockLedger:
        MockLedger.return_value.history.return_value = {"trades": []}
        result = PaperPositionManagerEngine().manage_open_positions()

    assert result["positions_checked"] == 0
    assert result["positions_closed"] == 0
    assert result["status"] == "PAPER_POSITION_MANAGER_NO_TRADES"


def test_manage_open_positions_does_not_quote_closed_trades():
    # A non-OPEN trade must be skipped without triggering live quote I/O.
    with patch(f"{MOD}.PaperTradeLedgerEngine") as MockLedger, \
         patch(f"{MOD}.MarketHoursEngine") as MockMH, \
         patch(f"{MOD}.TradeStationQuoteLiveEngine") as MockQuote:
        MockLedger.return_value.history.return_value = {
            "trades": [{"trade_id": "GL-2", "status": "CLOSED"}]
        }
        MockMH.return_value.status.return_value = {"is_regular_session": False}
        PaperPositionManagerEngine().manage_open_positions()
        MockQuote.return_value.get_quote.assert_not_called()
