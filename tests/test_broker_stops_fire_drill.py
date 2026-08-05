"""Broker-side stop FIRE DRILL: verify every open long has a resting stop covering its FULL quantity —
the gap the coarse 'symbol has a stop' check misses (a 3-share stop on a 6-share long). Read-only; no
orders placed. No network — the booking engine is faked.
"""

import json

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine as B


class _Book:
    def __init__(self, positions, orders):
        self._p, self._o = positions, orders

    def positions(self):
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}


def _pos(sym, qty):
    return {"Symbol": sym, "Quantity": qty}


def _stop(sym, qty):
    return {"StatusDescription": "Received", "OrderType": "StopMarket",
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
