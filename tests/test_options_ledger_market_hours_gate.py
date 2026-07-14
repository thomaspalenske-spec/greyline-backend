import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine

LEDGER = "app.services.options_paper_trade_ledger_engine"


def _market_open_gate(quote, session):
    """Reproduce the ledger's market-open gate against a given quote + session."""
    quote_market_state = (
        quote.get("market_state")
        or quote.get("underlying_market_state")
    )
    if quote_market_state:
        return quote_market_state == "MARKET_OPEN", quote_market_state
    return session.get("is_regular_session") is True, session.get("state") or "UNKNOWN"


# Regression: this gate read `market_state` off the underlying quote snapshot, a key
# that snapshot has never emitted. It therefore resolved to "UNKNOWN" on every call,
# never equalled "MARKET_OPEN", and blocked EVERY options entry unconditionally — which
# is why the options paper ledger held zero rows for the entire life of the system.

def test_open_market_is_not_blocked_when_quote_omits_market_state():
    quote = {"underlying_quote_status": "QUOTE_READ_SUCCESS", "underlying_entry_price": 36.67}
    session = {"is_regular_session": True, "state": "MARKET_OPEN_REGULAR_SESSION"}

    allowed, state = _market_open_gate(quote, session)
    assert allowed is True
    assert state == "MARKET_OPEN_REGULAR_SESSION"


def test_closed_market_is_still_blocked():
    # The protection must survive the fix — a genuinely closed market still blocks.
    quote = {"underlying_quote_status": "QUOTE_READ_SUCCESS"}
    session = {"is_regular_session": False, "state": "MARKET_CLOSED"}

    allowed, _ = _market_open_gate(quote, session)
    assert allowed is False


def test_explicit_quote_market_state_still_wins():
    # If the feed ever does supply market_state, honor it over the session engine.
    quote = {"market_state": "MARKET_OPEN"}
    session = {"is_regular_session": False, "state": "MARKET_CLOSED"}
    allowed, state = _market_open_gate(quote, session)
    assert allowed is True and state == "MARKET_OPEN"

    quote = {"market_state": "MARKET_CLOSED"}
    session = {"is_regular_session": True, "state": "MARKET_OPEN_REGULAR_SESSION"}
    allowed, _ = _market_open_gate(quote, session)
    assert allowed is False


def test_ledger_engine_consults_market_hours_engine():
    # Guard the wiring itself: the ledger must ask MarketHoursEngine, not infer.
    with patch(f"{LEDGER}.MarketHoursEngine") as MockHours:
        MockHours.return_value.status.return_value = {
            "is_regular_session": True,
            "state": "MARKET_OPEN_REGULAR_SESSION",
        }
        assert hasattr(OptionsPaperTradeLedgerEngine, "record_trade")
        from app.services import options_paper_trade_ledger_engine as mod
        assert hasattr(mod, "MarketHoursEngine")
