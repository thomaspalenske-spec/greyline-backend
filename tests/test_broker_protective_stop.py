"""Broker-side disaster stops: must protect real positions, must NEVER enable a double-sell,
and must stay off unless deliberately armed."""

import pytest

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine


class _FakeBooking:
    def __init__(self, positions, orders=None):
        self._p, self._o, self.placed, self.cancelled = positions, orders or [], [], []

    def positions(self):
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}

    def place_order(self, symbol, qty, action="SELL", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        self.placed.append({"symbol": symbol, "qty": qty, "action": action,
                            "order_type": order_type, "stop_price": stop_price, "tif": tif})
        return {"ok": True, "order_id": 1, "http_status": 200}

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        return {"http_status": 200}


def _pos(sym, qty, avg, short=False):
    return {"Symbol": sym, "Quantity": str(qty), "AveragePrice": str(avg),
            "LongShort": "Short" if short else "Long"}


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    return BrokerProtectiveStopEngine()


def test_disabled_by_default_places_nothing(monkeypatch):
    """New order-placing behaviour must never switch itself on."""
    monkeypatch.delenv("GREYLINE_BROKER_PROTECTIVE_STOPS", raising=False)
    e = BrokerProtectiveStopEngine()
    r = e.ensure_stops()
    assert r["status"] == "PROTECTIVE_STOPS_DISABLED" and r["placed"] == 0


def test_places_a_resting_stop_sized_from_the_LIVE_position(armed, monkeypatch):
    fake = _FakeBooking([_pos("AAPL", 10, 200.0)])
    monkeypatch.setattr(armed, "_booking", lambda: fake)
    r = armed.ensure_stops()
    assert r["placed"] == 1
    o = fake.placed[0]
    assert o["qty"] == 10                      # from the broker, never a ledger count
    assert o["order_type"] == "StopMarket" and o["tif"] == "GTC"
    assert o["stop_price"] == pytest.approx(200.0 * 0.65, abs=0.01)


def test_stop_sits_far_below_the_doctrine_stop_so_software_exits_first(armed):
    """A failsafe that races the strategy's own stop replaces a considered exit with a dumb one."""
    assert armed.DISASTER_STOP_PCT >= 0.25     # doctrine ATR stop is typically 8-20%


def test_never_double_protects_an_already_protected_symbol(armed, monkeypatch):
    """Two resting sells on one position is a short waiting to happen."""
    existing = [{"StatusDescription": "Queued", "OrderType": "StopMarket",
                 "Legs": [{"Symbol": "AAPL", "BuyOrSell": "Sell"}]}]
    fake = _FakeBooking([_pos("AAPL", 10, 200.0)], existing)
    monkeypatch.setattr(armed, "_booking", lambda: fake)
    r = armed.ensure_stops()
    assert r["placed"] == 0
    assert any(s["reason"] == "already protected" for s in r["skipped"])


def test_clear_stop_cancels_before_a_software_close(armed, monkeypatch):
    """THE double-sell guard: the resting order must be cancelled before software sells."""
    existing = [{"OrderID": 99, "StatusDescription": "Queued", "OrderType": "StopMarket",
                 "Legs": [{"Symbol": "AAPL", "BuyOrSell": "Sell"}]}]
    fake = _FakeBooking([_pos("AAPL", 10, 200.0)], existing)
    monkeypatch.setattr(armed, "_booking", lambda: fake)
    r = armed.clear_stop("AAPL")
    assert 99 in fake.cancelled and r["status"] == "PROTECTIVE_STOP_CLEARED"


def test_short_positions_are_not_given_a_sell_stop(armed, monkeypatch):
    fake = _FakeBooking([_pos("AAPL", 10, 200.0, short=True)])
    monkeypatch.setattr(armed, "_booking", lambda: fake)
    assert armed.ensure_stops()["placed"] == 0


def test_option_stop_lands_on_the_valid_price_grid(armed, monkeypatch):
    """Off-grid option prices are rejected outright by TradeStation."""
    fake = _FakeBooking([_pos("ALAB 260828C315", 1, 65.55)])
    monkeypatch.setattr(armed, "_booking", lambda: fake)
    armed.ensure_stops()
    sp = fake.placed[0]["stop_price"]
    assert abs(round(sp / 0.05) * 0.05 - sp) < 1e-9, f"{sp} off the $0.05 grid"


def test_working_close_order_never_gets_a_stop_stacked_on_it(monkeypatch):
    """A position already being closed must not also get a protective stop.

    Both could fill and sell the same position twice, which at the broker means going SHORT.
    This is the live case: options with working SELLTOCLOSE orders while equities are open.
    """
    from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine

    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    eng = BrokerProtectiveStopEngine()

    class FakeBooking:
        def positions(self):
            return {"response_json": {"Positions": [
                {"Symbol": "MRNA 260828C60", "Quantity": "1", "AveragePrice": "5.25",
                 "LongShort": "Long"},
                {"Symbol": "GLW", "Quantity": "6", "AveragePrice": "154.49", "LongShort": "Long"},
            ]}}

        def orders(self):
            return {"response_json": {"Orders": [
                {"OrderID": "1", "OrderType": "Limit", "StatusDescription": "Received",
                 "Legs": [{"Symbol": "MRNA 260828C60", "BuyOrSell": "SellToClose"}]},
            ]}}

    monkeypatch.setattr(eng, "_booking", lambda: FakeBooking())
    r = eng.ensure_stops(dry_run=True)

    stopped = {p["symbol"] for p in r["placed_detail"]}
    assert "MRNA 260828C60" not in stopped, "stacked a stop on a position already being closed"
    assert "GLW" in stopped, "the genuinely unprotected equity should still be stopped"

    s = eng.status()
    assert "MRNA 260828C60" not in s["unprotected"]
    assert "MRNA 260828C60" in s["closing_not_stopped"]
