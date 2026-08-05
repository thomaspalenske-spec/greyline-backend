"""Broker-side stop FIRE DRILL: verify every open long has a resting stop covering its FULL quantity —
the gap the coarse 'symbol has a stop' check misses (a 3-share stop on a 6-share long). Read-only; no
orders placed. No network — the booking engine is faked.
"""

import json

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine as B


class _Book:
    """Stateful fake: place_order adds a working stop; cancel_order removes it (unless cancel_works=False,
    to exercise the CONFIRM guard). Lets us test cancel-CONFIRM-replace without a broker."""
    def __init__(self, positions, orders, cancel_works=True, reads_ok=True):
        self._p, self._o = positions, list(orders)
        self.cancel_works = cancel_works
        self._reads_ok = reads_ok
        self._seq = 100

    def positions(self):
        return {"ok": self._reads_ok, "response_json": {"Positions": self._p}}

    def orders(self):
        return {"ok": self._reads_ok, "response_json": {"Orders": self._o}}

    def place_order(self, sym, qty, action=None, order_type=None, stop_price=None, tif=None):
        self._seq += 1
        oid = f"o{self._seq}"
        self._o.append(_stop(sym, qty, oid))
        return {"ok": True, "order_id": oid, "http_status": 200}

    def cancel_order(self, oid):
        if self.cancel_works:
            self._o = [o for o in self._o if o.get("OrderID") != oid]
        return {"http_status": 200}


def _pos(sym, qty, avg=100.0):
    return {"Symbol": sym, "Quantity": qty, "AveragePrice": avg, "LongShort": "Long"}


def _stop(sym, qty, oid="s1"):
    return {"StatusDescription": "Received", "OrderType": "StopMarket", "OrderID": oid,
            "Legs": [{"Symbol": sym, "BuyOrSell": "Sell", "QuantityRemaining": qty}]}


def _wire(monkeypatch, tmp_path, positions, orders, armed=True, vrp=frozenset()):
    if armed:
        monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    else:
        monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "false")
    monkeypatch.setattr(B, "_booking", lambda self: _Book(positions, orders))
    monkeypatch.setattr(B, "_vrp_leg_symbols", staticmethod(lambda: set(vrp)))
    monkeypatch.setattr(B, "MARKER", tmp_path / "fire_drill.json")


def test_full_coverage_is_verified(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [_pos("DBC", 16)], [_stop("DBC", 16)])
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_VERIFIED" and r["verified"] == 1 and r["gaps"] == []


def test_partial_coverage_is_a_gap(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [_pos("DBC", 16)], [_stop("DBC", 10)])   # 10 of 16 covered
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_GAP"
    assert r["partial"] and r["partial"][0]["symbol"] == "DBC" and r["partial"][0]["stop_qty"] == 10


def test_no_stop_is_unprotected(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [_pos("IWM", 6)], [])
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_GAP"
    assert r["unprotected"] and r["unprotected"][0]["symbol"] == "IWM"


def test_over_coverage_is_a_gap(monkeypatch, tmp_path):
    # stop bigger than the position (position shrank, stop not cleared) — oversell-SHORT hazard if it fires
    _wire(monkeypatch, tmp_path, [_pos("IWM", 6)], [_stop("IWM", 10)])
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_GAP"
    assert r["over_covered"] and r["over_covered"][0]["symbol"] == "IWM"


# ---- coverage-aware ensure_stops (top-up via cancel-CONFIRM-replace) ----

def _wire_topup(monkeypatch, tmp_path, book, armed=True, topup=True):
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true" if armed else "false")
    monkeypatch.setenv("GREYLINE_BROKER_STOP_TOPUP", "true" if topup else "false")
    monkeypatch.setattr(B, "_booking", lambda self: book)
    monkeypatch.setattr(B, "_vrp_leg_symbols", staticmethod(lambda: set()))


def test_partial_growth_adds_only_the_shortfall(monkeypatch, tmp_path):
    # position grew 16->64; ADD 48 (no cancel) -> resting total becomes EXACTLY 64, no uncovered window
    book = _Book([_pos("SVXY", 64)], [_stop("SVXY", 16, "s1")])
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().ensure_stops()
    assert r["topped_up"] == 1 and r["topup_detail"][0]["action"] == "topup_added"
    assert r["topup_detail"][0]["add_qty"] == 48 and r["topup_detail"][0]["to_qty"] == 64
    stops = [o for o in book._o if "stop" in o["OrderType"].lower()]
    assert sum(o["Legs"][0]["QuantityRemaining"] for o in stops) == 64   # old kept + shortfall added
    assert len(stops) == 2                                               # never cancelled -> no gap window


def test_over_coverage_reduces_via_cancel_replace(monkeypatch, tmp_path):
    # position shrank to 6 but a 10-qty stop still rests (oversell hazard) -> cancel-CONFIRM-replace to 6
    book = _Book([_pos("IWM", 6)], [_stop("IWM", 10, "s1")])
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().ensure_stops()
    assert r["topped_up"] == 1 and r["topup_detail"][0]["action"] == "topup_replaced"
    stops = [o for o in book._o if "stop" in o["OrderType"].lower()]
    assert len(stops) == 1 and stops[0]["Legs"][0]["QuantityRemaining"] == 6


def test_over_coverage_aborts_if_cancel_not_confirmed(monkeypatch, tmp_path):
    book = _Book([_pos("IWM", 6)], [_stop("IWM", 10, "s1")], cancel_works=False)
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().ensure_stops()
    assert r["topped_up"] == 0 and any(e.get("action") == "topup_aborted" for e in r["errors"])
    stops = [o for o in book._o if "stop" in o["OrderType"].lower()]
    assert len(stops) == 1 and stops[0]["Legs"][0]["QuantityRemaining"] == 10   # unchanged, not stacked


def test_topup_disarmed_leaves_partial_untouched(monkeypatch, tmp_path):
    book = _Book([_pos("SVXY", 64)], [_stop("SVXY", 16, "s1")])
    _wire_topup(monkeypatch, tmp_path, book, topup=False)
    r = B().ensure_stops()
    assert r["topped_up"] == 0
    assert any("top-up" in s.get("reason", "").lower() for s in r["skipped"])


def test_unprotected_still_places_full_qty(monkeypatch, tmp_path):
    book = _Book([_pos("IWM", 6)], [])
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().ensure_stops()
    assert r["placed"] == 1 and r["placed_detail"][0]["qty"] == 6


def test_degraded_read_places_nothing_fail_closed(monkeypatch, tmp_path):
    # a FAILED orders/positions read returns empty -> without the guard, ensure_stops would place a stop
    # that stacks on an existing (unread) one and oversell. It must fail closed and place NOTHING.
    book = _Book([_pos("SVXY", 64)], [_stop("SVXY", 16, "s1")], reads_ok=False)
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().ensure_stops()
    assert r["status"] == "PROTECTIVE_STOPS_READ_DEGRADED"
    assert r["placed"] == 0 and r["topped_up"] == 0
    stops = [o for o in book._o if "stop" in o["OrderType"].lower()]
    assert len(stops) == 1                          # unchanged — nothing placed on the degraded read


def test_fire_drill_degraded_read_no_false_gap(monkeypatch, tmp_path):
    book = _Book([_pos("SVXY", 64)], [], reads_ok=False)   # empty orders from a failed read
    _wire_topup(monkeypatch, tmp_path, book)
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_DRILL_DEGRADED"     # NOT a false 'unprotected' gap


def test_disarmed_when_off(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [_pos("IWM", 6)], [], armed=False)
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_DISARMED" and r["armed"] is False


def test_short_and_vrp_legs_are_not_flagged(monkeypatch, tmp_path):
    # a short position needs no sell-stop; a VRP condor leg must NEVER be stopped (naked-short trap)
    _wire(monkeypatch, tmp_path, [_pos("SVXY", -8), _pos("SPY 260101C500", 1)], [],
          vrp={"SPY 260101C500"})
    r = B().fire_drill()
    assert r["status"] == "BROKER_STOPS_VERIFIED" and r["long_positions"] == 0


def test_fire_drill_if_due_pages_on_gap_and_gates(monkeypatch, tmp_path):
    import app.services.external_alert_engine as eae
    _wire(monkeypatch, tmp_path, [_pos("IWM", 6)], [])
    calls = []
    monkeypatch.setattr(eae.ExternalAlertEngine, "dispatch",
                        lambda self, title, message, **k: calls.append(k.get("severity")) or {"status": "X"})
    r = B().fire_drill_if_due()                       # never run -> due -> GAP -> pages CRITICAL
    assert r["status"] == "BROKER_STOPS_GAP" and calls == ["CRITICAL"]
    assert (tmp_path / "fire_drill.json").exists()
    r2 = B().fire_drill_if_due()                      # within DUE_HOURS -> gated
    assert r2["status"] == "BROKER_STOPS_DRILL_NOT_DUE"
    assert len(calls) == 1                            # not re-paged
