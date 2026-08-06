"""Churn guard: a sleeve must count its OWN resting (unfilled) orders as part of its position, so it
never re-posts a shortfall it already has an order out for. Regression for the 2026-08-04 loop where
carry stacked SVXY to 154 shares (buy ~20 every cycle) before a single 154-share dump. No network —
the booking engine's orders() read is faked; no orders are placed."""

from app.services.in_flight_orders_engine import InFlightOrdersEngine as IFO


class _Book:
    def __init__(self, orders, ok=True):
        self._o, self._ok = orders, ok

    def orders(self):
        return {"ok": self._ok, "response_json": {"Orders": self._o}}


def _ord(sym, side, qty, status="Received", remaining=None):
    return {"StatusDescription": status,
            "Legs": [{"Symbol": sym, "BuyOrSell": side,
                      "QuantityRemaining": qty if remaining is None else remaining, "Quantity": qty}]}


def test_working_buy_counts_toward_position():
    snap = IFO.snapshot(booking=_Book([_ord("SVXY", "Buy", 20)]))
    assert snap["ok"] and snap["net"] == {"SVXY": 20} and snap["count"] == 1
    assert IFO.net_working("svxy", snapshot=snap)["net"] == 20


def test_buys_and_sells_net_signed():
    snap = IFO.snapshot(booking=_Book([_ord("IWM", "Buy", 5), _ord("IWM", "Sell", 2),
                                       _ord("QQQM", "Buy", 3)]))
    assert snap["net"] == {"IWM": 3, "QQQM": 3}


def test_only_working_status_is_counted():
    # a Filled / Cancelled order no longer reserves shares (Filled already shows in `held`)
    snap = IFO.snapshot(booking=_Book([_ord("SVXY", "Buy", 20, status="Filled"),
                                       _ord("SVXY", "Buy", 8, status="Cancelled"),
                                       _ord("SVXY", "Buy", 4, status="Received")]))
    assert snap["net"] == {"SVXY": 4}


def test_partial_fill_counts_only_the_remainder():
    snap = IFO.snapshot(booking=_Book([_ord("DBC", "Buy", 100, status="PartiallyFilled", remaining=30)]))
    assert snap["net"] == {"DBC": 30}


def test_degraded_read_is_not_ok_and_empty():
    snap = IFO.snapshot(booking=_Book([_ord("SVXY", "Buy", 20)], ok=False))
    assert snap["ok"] is False and snap["net"] == {}
    # a caller asking net_working on a degraded read gets ok=False -> must refuse to open
    assert IFO.net_working("SVXY", snapshot=snap) == {"ok": False, "net": 0}


def test_read_exception_is_not_ok():
    class _Boom:
        def orders(self):
            raise RuntimeError("network down")
    snap = IFO.snapshot(booking=_Boom())
    assert snap["ok"] is False and snap["net"] == {}


def test_the_churn_scenario_yields_no_new_order():
    # target 16, filled 0, but a resting buy 16 already rests -> effective 16 -> delta 0 (no duplicate).
    # This is the exact guard that stops the stack: WITHOUT counting the resting order, delta would be
    # +16 and a SECOND buy 16 would be posted this cycle.
    snap = IFO.snapshot(booking=_Book([_ord("SVXY", "Buy", 16)]))
    filled_held, target = 0, 16
    effective = filled_held + IFO.net_working("SVXY", snapshot=snap)["net"]
    assert target - effective == 0
