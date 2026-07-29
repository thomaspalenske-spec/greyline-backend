"""Hermetic tests for LegacyOrderlyLiquidationEngine — no live broker, no real orders.

Covers the safety-critical invariants: sizing from the LIVE position, one-close-per-symbol with
cancel-confirm-before-replace, correct trade action per instrument, the price ladder
(patient -> mid -> marketable-at-bid), and self-termination when flat.
"""

import app.services.tradestation_sim_booking_engine as booking_mod
import app.services.tradestation_quote_live_engine as quote_mod
from app.services.legacy_orderly_liquidation_engine import LegacyOrderlyLiquidationEngine as ENG


class FakeBook:
    def __init__(self, positions, orders=None):
        self._positions = positions            # {symbol: qty}
        self._orders = list(orders or [])      # list of order dicts
        self.placed = []
        self.cancelled = []
        self.cancel_removes = True             # whether cancel actually clears the order

    def positions(self):
        return {"response_json": {"Positions": [
            {"Symbol": s, "Quantity": str(q)} for s, q in self._positions.items()]}}

    def orders(self):
        return {"response_json": {"Orders": self._orders}}

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        if self.cancel_removes:
            self._orders = [o for o in self._orders if o.get("OrderID") != oid]
        return {"http_status": 200}

    def place_order(self, symbol, qty, action="BUY", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        self.placed.append({"symbol": symbol, "qty": qty, "action": action,
                            "order_type": order_type, "limit_price": limit_price, "tif": tif})
        return {"ok": True, "order_id": "NEW1"}


class FakeQuotes:
    def __init__(self, quotes):
        self._q = quotes                       # {symbol_or_ticker: (bid, ask)}

    def get_quote(self, sym):
        b, a = self._q.get(sym, (0.0, 0.0))
        return {"response_json": {"Quotes": [{"Bid": b, "Ask": a}]}}


def _sell_order(oid, symbol, price):
    return {"OrderID": oid, "StatusDescription": "Queued", "OrderType": "Limit",
            "LimitPrice": str(price), "Legs": [{"Symbol": symbol, "BuyOrSell": "Sell"}]}


def _wire(monkeypatch, book, quotes, minutes=2.0, enabled=True):
    monkeypatch.setenv("GREYLINE_LEGACY_LIQUIDATION_ENABLED", "true" if enabled else "false")
    monkeypatch.setattr(booking_mod, "TradeStationSimBookingEngine", lambda: book)
    monkeypatch.setattr(quote_mod, "TradeStationQuoteLiveEngine", lambda: quotes)
    monkeypatch.setattr(ENG, "_minutes_since_open", lambda self, now=None: minutes)


def test_disabled_is_noop(monkeypatch):
    book = FakeBook({"ALTO": 196})
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}), enabled=False)
    r = ENG().run_cycle(is_regular_session=True)
    assert r["status"] == "LEGACY_LIQUIDATION_DISABLED"
    assert book.placed == []


def test_market_closed_is_noop(monkeypatch):
    book = FakeBook({"ALTO": 196})
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}))
    r = ENG().run_cycle(is_regular_session=False)
    assert r["status"] == "LEGACY_LIQUIDATION_MARKET_CLOSED"
    assert book.placed == []


def test_flat_self_terminates(monkeypatch):
    book = FakeBook({})                         # nothing held
    _wire(monkeypatch, book, FakeQuotes({}))
    r = ENG().run_cycle(is_regular_session=True)
    assert r["status"] == "LEGACY_LIQUIDATION_FLAT"
    assert book.placed == []


def test_equity_marketable_below_bid_sized_from_live(monkeypatch):
    book = FakeBook({"ALTO": 196})
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}))
    ENG().run_cycle(is_regular_session=True)
    assert len(book.placed) == 1
    o = book.placed[0]
    assert o["symbol"] == "ALTO" and o["action"] == "SELL" and o["qty"] == 196
    assert abs(o["limit_price"] - round(4.64 * 0.98, 2)) < 1e-9   # marketable, inside the band


def test_option_patient_near_ask_selltoclose(monkeypatch):
    book = FakeBook({"ALAB 260828C315": 1})
    _wire(monkeypatch, book, FakeQuotes({"ALAB 260828C315": (32.85, 39.30)}), minutes=2.0)
    ENG().run_cycle(is_regular_session=True)
    o = book.placed[0]
    assert o["symbol"] == "ALAB 260828C315" and o["action"] == "SELLTOCLOSE"
    mid = (32.85 + 39.30) / 2
    assert o["limit_price"] > mid                                 # near the ask, capturing spread


def test_option_urgent_marketable_at_bid(monkeypatch):
    book = FakeBook({"ALAB 260828C315": 1})
    _wire(monkeypatch, book, FakeQuotes({"ALAB 260828C315": (32.85, 39.30)}), minutes=40.0)
    ENG().run_cycle(is_regular_session=True)
    o = book.placed[0]
    assert o["action"] == "SELLTOCLOSE"
    assert abs(o["limit_price"] - 32.85) < 1e-9                   # marketable limit at the bid


def test_existing_good_close_is_kept_no_churn(monkeypatch):
    # a resting close already at (near) the desired equity price -> no cancel, no re-place
    desired = round(4.64 * 0.98, 2)
    book = FakeBook({"ALTO": 196}, orders=[_sell_order("OLD", "ALTO", desired)])
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}))
    r = ENG().run_cycle(is_regular_session=True)
    assert book.placed == [] and book.cancelled == []
    assert r["actions"][0]["action"] == "kept"


def test_stale_close_is_cancelled_then_replaced(monkeypatch):
    book = FakeBook({"ALTO": 196}, orders=[_sell_order("OLD", "ALTO", 2.40)])  # far from desired
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}))
    ENG().run_cycle(is_regular_session=True)
    assert "OLD" in book.cancelled
    assert len(book.placed) == 1 and book.placed[0]["qty"] == 196


def test_cancel_not_confirmed_skips_place_no_double_sell(monkeypatch):
    book = FakeBook({"ALTO": 196}, orders=[_sell_order("OLD", "ALTO", 2.40)])
    book.cancel_removes = False                 # broker fails to clear the working order
    _wire(monkeypatch, book, FakeQuotes({"ALTO": (4.64, 4.66)}))
    r = ENG().run_cycle(is_regular_session=True)
    assert book.placed == []                    # never stack a second live sell
    assert "cancel not confirmed" in r["actions"][0]["skipped"]


def test_non_target_symbol_is_ignored(monkeypatch):
    # a VRP-OS position (e.g. SPY condor leg) must never be touched
    book = FakeBook({"SPY 260828P600": 3})
    _wire(monkeypatch, book, FakeQuotes({"SPY 260828P600": (5.0, 6.0)}))
    r = ENG().run_cycle(is_regular_session=True)
    assert r["status"] == "LEGACY_LIQUIDATION_FLAT"
    assert book.placed == []
