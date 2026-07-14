import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.options_cycle_engine as oce
from app.services.options_cycle_engine import OptionsCycleEngine

CHAIN = "app.services.options_cycle_engine.TradeStationOptionChainLiveEngine"


def _expirations(*dates):
    return {"expirations": [f"{d}T00:00:00Z" for d in dates]}


# ---- expiration selection ----
# Regression: expiration was hardcoded to "2026-07-17" and the sweep never overrode it.
# Once the calendar drifted inside OptionsEntryQualityGateEngine's 7-DTE floor, that
# frozen date made the gate reject EVERY options entry regardless of signal strength.

TODAY = date(2026, 7, 14)


def test_selects_nearest_expiration_clearing_the_7_dte_floor():
    with patch(CHAIN) as MockChain:
        MockChain.return_value.get_expirations.return_value = _expirations(
            "2026-07-15",  # 1 DTE  - too soon
            "2026-07-17",  # 3 DTE  - the old hardcoded date, too soon
            "2026-07-24",  # 10 DTE - first eligible
            "2026-07-31",  # 17 DTE
        )
        picked = OptionsCycleEngine()._select_expiration("IBIT", today=TODAY)
        assert picked == "2026-07-24"


def test_does_not_return_the_stale_hardcoded_date():
    with patch(CHAIN) as MockChain:
        MockChain.return_value.get_expirations.return_value = _expirations(
            "2026-07-17", "2026-07-24"
        )
        assert OptionsCycleEngine()._select_expiration("IBIT", today=TODAY) != "2026-07-17"


def test_falls_back_to_furthest_expiry_when_none_clear_the_floor():
    # A thin/short chain shouldn't hard-fail; hand the furthest contract to the
    # quality gate and let it decide, rather than returning a stale literal.
    with patch(CHAIN) as MockChain:
        MockChain.return_value.get_expirations.return_value = _expirations(
            "2026-07-15", "2026-07-17"
        )
        assert OptionsCycleEngine()._select_expiration("IBIT", today=TODAY) == "2026-07-17"


def test_no_expirations_listed_returns_none():
    with patch(CHAIN) as MockChain:
        MockChain.return_value.get_expirations.return_value = {"expirations": []}
        assert OptionsCycleEngine()._select_expiration("IBIT") is None


def test_explicit_expiration_is_respected():
    # Callers that pass an expiration must still win — selection is only a default.
    with patch(CHAIN) as MockChain:
        MockChain.return_value.get_chain_snapshot.return_value = {"contracts": []}
        OptionsCycleEngine().run(symbol="IBIT", option_type="CALL", expiration="2026-09-18")
        kwargs = MockChain.return_value.get_chain_snapshot.call_args.kwargs
        assert kwargs["expiration"] == "2026-09-18"
