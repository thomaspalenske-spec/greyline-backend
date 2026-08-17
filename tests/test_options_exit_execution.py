"""Option exits must be PRICED limits, not naked market orders — the single biggest controllable
cost in an OTM book. Urgency-tiered: stops fill now with a floor; take-profits capture spread."""

import pytest

from app.services.options_exit_execution_engine import OptionsExitExecutionEngine


# --------------------------------------------------------------- policy logic

def test_classify_urgency_from_reason():
    e = OptionsExitExecutionEngine()
    assert e.classify("OPTIONS_DOCTRINE_STOP") == "urgent"
    assert e.classify("OPTIONS_MATURITY_1_BUSINESS_DAY") == "urgent"
    assert e.classify("OPTIONS_TP2") == "patient"
    assert e.classify("OPTIONS_TP4_TRAIL") == "urgent"     # a trailing stop firing must get out


def test_urgent_exit_is_marketable_limit_at_the_bid_not_market():
    """A stop must fill, but with a floor — never a naked market order that a thin book can fill
    through."""
    p = OptionsExitExecutionEngine().price_exit(bid=3.00, ask=3.40, reason="OPTIONS_DOCTRINE_STOP")
    assert p["order_type"] == "Limit"
    assert p["limit_price"] == 3.00        # AT the bid: fills now, cannot fill worse than the bid
    assert p["forced_market"] is False and p["skip"] is False


def test_patient_take_profit_prices_near_the_ask_to_capture_spread():
    p = OptionsExitExecutionEngine().price_exit(bid=3.00, ask=3.40, reason="OPTIONS_TP1")
    assert p["order_type"] == "Limit"
    # 0.25 of the 0.40 spread below the 3.40 ask -> 3.30, and strictly above the bid
    assert p["limit_price"] == 3.30
    assert 3.00 < p["limit_price"] <= 3.40


def test_limit_snaps_to_the_nickel_grid():
    # bid/ask on the nickel grid -> the patient limit must land on it, or TradeStation rejects it
    p = OptionsExitExecutionEngine().price_exit(bid=1.05, ask=1.55, reason="OPTIONS_TP1")
    assert abs(round(p["limit_price"] / 0.05) * 0.05 - p["limit_price"]) < 1e-9


def test_urgent_with_no_quote_falls_back_to_market_but_flags_it():
    p = OptionsExitExecutionEngine().price_exit(bid=0, ask=0, reason="OPTIONS_MATURITY_1_BUSINESS_DAY")
    assert p["order_type"] == "Market"
    assert p["forced_market"] is True and p["skip"] is False


def test_patient_with_no_quote_is_skipped_never_market_dumped():
    """We never blind-sell a winner. No quote on a take-profit -> skip and retry next cycle."""
    p = OptionsExitExecutionEngine().price_exit(bid=0, ask=0, reason="OPTIONS_TP1")
    assert p["skip"] is True
    assert p["order_type"] is None


# ----------------------------------------------------- integration via SIM close

class _FakeBooking:
    def __init__(self, orders=None):
        self.placed = []
        self.cancelled = []
        self._orders = orders or []

    def positions(self):
        return {"response_json": {"Positions": [
            {"Symbol": "MRNA 260828C60", "Quantity": "4", "LongShort": "Long"}]}}

    def orders(self):
        return {"response_json": {"Orders": self._orders}}

    def place_order(self, symbol, qty, action="BUY", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        self.placed.append({"symbol": symbol, "qty": qty, "action": action,
                            "order_type": order_type, "limit_price": limit_price})
        return {"ok": True, "order_id": "NEW1", "http_status": 200}

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"ok": True, "order_id": order_id, "http_status": 200}


def _engine(monkeypatch, booking, bid=3.00, ask=3.40):
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
    e = GreyLineSimExecutionEngine()
    e.booking = booking
    monkeypatch.setattr(e, "_option_quote", lambda sym: (bid, ask, "tradestation"))
    return e


def test_close_places_a_limit_not_a_market_order(monkeypatch):
    b = _FakeBooking()
    e = _engine(monkeypatch, b)
    r = e.book_option_close("MRNA 260828C60", contracts=2, reason="OPTIONS_TP1")
    assert r["ok"] and r["order_type"] == "Limit"
    assert b.placed[0]["order_type"] == "Limit"
    assert b.placed[0]["limit_price"] == 3.30       # patient, near the ask
    assert b.placed[0]["qty"] == 2                    # partial tranche, capped at live


def test_urgent_stop_cancels_a_resting_take_profit_then_sells(monkeypatch):
    """A patient limit resting on the contract must never block a stop. Cancel-replace."""
    resting = [{"OrderID": "OLD9", "StatusDescription": "Received",
                "Legs": [{"Symbol": "MRNA 260828C60", "BuyOrSell": "SellToClose"}]}]
    b = _FakeBooking(orders=resting)
    e = _engine(monkeypatch, b)
    r = e.book_option_close("MRNA 260828C60", contracts=4, reason="OPTIONS_DOCTRINE_STOP")
    assert "OLD9" in b.cancelled            # the resting take-profit was pulled first
    assert r["order_type"] == "Limit" and b.placed[0]["limit_price"] == 3.00  # marketable at bid


def test_patient_tranche_does_not_stack_on_an_existing_resting_close(monkeypatch):
    resting = [{"OrderID": "OLD9", "StatusDescription": "Received",
                "Legs": [{"Symbol": "MRNA 260828C60", "BuyOrSell": "SellToClose"}]}]
    b = _FakeBooking(orders=resting)
    e = _engine(monkeypatch, b)
    r = e.book_option_close("MRNA 260828C60", contracts=1, reason="OPTIONS_TP2")
    assert r["status"] == "SKIPPED_WORKING_CLOSE_EXISTS"
    assert b.placed == [] and b.cancelled == []
