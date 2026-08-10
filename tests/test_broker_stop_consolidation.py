"""Protective-stop hardening: consolidate multiple resting stops to ONE, and never stack a fresh stop on
a flapping/degraded orders read. Root cause of the 2026-08-10 DBC×5 / QQQM×4 stacking: the 'fully covered'
check skipped consolidation, and a 200-but-empty orders read defeated the 'already protected' check.
No network — the booking engine is faked; no real orders.
"""

import json
from datetime import datetime

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine as B


def _pos(sym, qty, avg=100.0):
    return {"Symbol": sym, "Quantity": qty, "AveragePrice": avg, "LongShort": "Long"}


def _stop(sym, qty, oid="s1"):
    return {"StatusDescription": "Received", "OrderType": "StopMarket", "OrderID": oid,
            "Legs": [{"Symbol": sym, "BuyOrSell": "Sell", "QuantityRemaining": qty}]}


class _Book:
    def __init__(self, positions, orders):
        self._p, self._o = positions, list(orders)
        self._seq = 100

    def positions(self):
        return {"ok": True, "response_json": {"Positions": self._p}}

    def orders(self):
        return {"ok": True, "response_json": {"Orders": self._o}}

    def place_order(self, sym, qty, action=None, order_type=None, stop_price=None, tif=None):
        self._seq += 1
        oid = f"o{self._seq}"
        self._o.append(_stop(sym, qty, oid))
        return {"ok": True, "order_id": oid, "http_status": 200}

    def cancel_order(self, oid):
        self._o = [o for o in self._o if o.get("OrderID") != oid]
        return {"http_status": 200}


def _wire(monkeypatch, tmp_path, book, topup=False):
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    monkeypatch.setenv("GREYLINE_BROKER_STOP_TOPUP", "true" if topup else "false")
    monkeypatch.setattr(B, "_vrp_leg_symbols", staticmethod(lambda: set()))
    monkeypatch.setattr(B, "MARKER", tmp_path / "fd.json")
    monkeypatch.setattr(B, "COVERAGE_MARKER", tmp_path / "cov.json")
    monkeypatch.setattr(B, "_booking", lambda self, _b=book: _b)


def _dbc_stops(book):
    return [o for o in book._o if o["Legs"][0]["Symbol"] == "DBC"]


def test_multiple_stops_consolidate_to_one(monkeypatch, tmp_path):
    # DBC held 27 with FIVE resting stops (summing to 27) — the observed stacking. Consolidate to one.
    orders = [_stop("DBC", 5, "a"), _stop("DBC", 5, "b"), _stop("DBC", 5, "c"),
              _stop("DBC", 5, "d"), _stop("DBC", 7, "e")]
    book = _Book([_pos("DBC", 27)], orders)
    _wire(monkeypatch, tmp_path, book, topup=True)          # consolidation uses the top-up cancel-replace
    B().ensure_stops()
    stops = _dbc_stops(book)
    assert len(stops) == 1                                   # collapsed 5 -> 1
    assert int(stops[0]["Legs"][0]["QuantityRemaining"]) == 27   # full position covered


def test_consolidation_needs_topup_gate(monkeypatch, tmp_path):
    book = _Book([_pos("DBC", 27)], [_stop("DBC", 20, "a"), _stop("DBC", 7, "b")])
    _wire(monkeypatch, tmp_path, book, topup=False)          # top-up disarmed
    res = B().ensure_stops()
    assert len(_dbc_stops(book)) == 2                        # left as-is (not touched without the gate)
    assert any("consolidation needs" in str(s.get("reason", "")) for s in res.get("skipped", []))


def test_anti_stack_skips_when_read_shows_zero_but_recently_covered(monkeypatch, tmp_path):
    # DBC was CONFIRMED covered 1 min ago; now the orders read shows NO stops (degraded/partial 200).
    # Placing would stack a duplicate on the unseen stop -> must SKIP.
    (tmp_path / "cov.json").write_text(json.dumps({"DBC": {"qty": 27, "at": datetime.utcnow().isoformat()}}))
    book = _Book([_pos("DBC", 27)], [])                     # held, but zero stops visible this read
    _wire(monkeypatch, tmp_path, book)
    res = B().ensure_stops()
    assert len(_dbc_stops(book)) == 0                        # did NOT place (no stack)
    assert any("anti-stack" in str(s.get("reason", "")) for s in res.get("skipped", []))


def test_first_placement_still_happens_without_prior_coverage(monkeypatch, tmp_path):
    # No prior coverage marker -> a genuinely unprotected long still gets its stop (guard must not block this)
    book = _Book([_pos("IWM", 6)], [])
    _wire(monkeypatch, tmp_path, book)
    B().ensure_stops()
    iwm = [o for o in book._o if o["Legs"][0]["Symbol"] == "IWM"]
    assert len(iwm) == 1 and int(iwm[0]["Legs"][0]["QuantityRemaining"]) == 6
