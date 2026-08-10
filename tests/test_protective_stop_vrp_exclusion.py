"""The broker protective-stop engine must NEVER stop a VRP condor leg.

On 2026-07-27 (first live VRP open) it placed StopMarket sells on the condor WINGS. A wing is the
defined-risk hedge; stopping it out strands the short leg NAKED (undefined risk) — the opposite of
protection. This locks in the exclusion: VRP-ledger legs are skipped; ordinary longs still get a stop.
"""

import pytest

from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine as BPS


@pytest.fixture(autouse=True)
def _isolate_cov_marker(monkeypatch, tmp_path):
    # isolate the anti-stack coverage marker so these tests don't read/write the shared real file
    monkeypatch.setattr(BPS, "COVERAGE_MARKER", tmp_path / "cov.json")


class FakeBook:
    def __init__(self, positions, orders=None):
        self._p = positions
        self._o = orders or []

    def positions(self):
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": self._o}}

    def place_order(self, *a, **k):
        return {"ok": True, "order_id": "X"}


def _pos(sym, qty, entry, ls="Long"):
    return {"Symbol": sym, "Quantity": str(qty), "AveragePrice": str(entry), "LongShort": ls}


def test_vrp_condor_wing_is_not_stopped(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    wing = "IWM 260904C313"
    eng = BPS()
    monkeypatch.setattr(eng, "_booking", lambda: FakeBook([_pos(wing, 1, 1.44)]))
    monkeypatch.setattr(BPS, "_vrp_leg_symbols", staticmethod(lambda: {wing.upper()}))
    r = eng.ensure_stops(dry_run=True)
    assert r["placed"] == 0                                              # no stop placed
    assert any(s["symbol"] == wing and "VRP condor leg" in s["reason"] for s in r["skipped"])


def test_ordinary_long_still_gets_a_stop(monkeypatch):
    # An ordinary EQUITY long (not a VRP leg, not premium-bounded) still gets a disaster stop.
    # (Long options are intentionally skipped elsewhere — loss is bounded by premium — so the
    # honest contrast to a VRP condor leg is a plain equity, which carries unbounded downside.)
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    sym = "GLW"
    eng = BPS()
    monkeypatch.setattr(eng, "_booking", lambda: FakeBook([_pos(sym, 10, 40.0)]))
    monkeypatch.setattr(BPS, "_vrp_leg_symbols", staticmethod(lambda: set()))   # not a VRP leg
    r = eng.ensure_stops(dry_run=True)
    assert r["placed"] == 1
    assert any(d["symbol"] == sym for d in r["placed_detail"])


def test_short_leg_never_stopped_regardless(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    short = "IWM 260904C311"
    eng = BPS()
    monkeypatch.setattr(eng, "_booking", lambda: FakeBook([_pos(short, -1, 1.71, ls="Short")]))
    monkeypatch.setattr(BPS, "_vrp_leg_symbols", staticmethod(lambda: {short.upper()}))
    r = eng.ensure_stops(dry_run=True)
    assert r["placed"] == 0                                              # shorts are never stopped


def test_status_excludes_condor_legs_from_unprotected(monkeypatch):
    """The BROKER_SIDE_PROTECTION guard reads status().unprotected. A condor leg must NOT be counted
    as unprotected (it is defined-risk by structure and correctly carries no per-leg stop) — else the
    guard cries wolf on legs it is right to leave un-stopped. Ordinary longs with no stop still flag."""
    monkeypatch.setenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "true")
    wing = "XLE 260918C65"
    ordinary = "GLW"
    eng = BPS()
    monkeypatch.setattr(eng, "_booking", lambda: FakeBook([_pos(wing, 1, 1.2), _pos(ordinary, 5, 40.0)]))
    monkeypatch.setattr(BPS, "_vrp_leg_symbols", staticmethod(lambda: {wing.upper()}))
    s = eng.status()
    assert wing.upper() in s["defined_risk_legs"]          # surfaced, not hidden
    assert wing.upper() not in s["unprotected"]            # NOT counted as unprotected
    assert ordinary.upper() in s["unprotected"]            # a real naked long still flags
