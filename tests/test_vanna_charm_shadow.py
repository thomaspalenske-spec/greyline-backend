"""Vanna/charm shadow: OPEX-window + negative-vanna LONG signal, forward-test open/exit (opex/stop), report
gating. Greeks + spot + OPEX date stubbed — no network, no orders, temp state."""

import json
from datetime import date

import pytest

from app.services.vanna_charm_shadow_engine import VannaCharmShadowEngine as V


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "STATE", tmp_path)
    monkeypatch.setattr(V, "OPEN", tmp_path / "open.json")
    monkeypatch.setattr(V, "CLOSED", tmp_path / "closed.jsonl")
    monkeypatch.setattr(V, "NAMES", ["SPY"])
    monkeypatch.setattr(V, "MARK_MARKER", tmp_path / "last_mark.json")
    monkeypatch.setattr(V, "MARK_INTERVAL_MIN", 0)                                # no rate-gate in tests
    monkeypatch.setattr(V, "_today", staticmethod(lambda: date(2026, 8, 13)))     # 6 biz days before 08-21 OPEX
    monkeypatch.setenv("GREYLINE_VANNA_CHARM_SHADOW", "true")
    # Force the shadow-tradeability RTH gate OPEN so these open/settle tests are time-independent (the gate
    # itself is tested in test_shadow_tradeability_gate). Without this they fail whenever the suite runs after hours.
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)
    yield


def _wire(monkeypatch, spot, net_vanna=-5e8, net_charm=2e8):
    monkeypatch.setattr(V, "_greeks", lambda self, n, _v=net_vanna, _c=net_charm: {"net_vanna": _v, "net_charm": _c, "date": "2026-08-13"})
    monkeypatch.setattr(V, "_spots", lambda self, names, _s=spot: {n: _s for n in names})


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_VANNA_CHARM_SHADOW", "false")
    assert V().mark()["status"] == "VANNA_SHADOW_DISABLED"


def test_next_opex_is_third_friday():
    assert V._next_opex() == date(2026, 8, 21)          # 3rd Friday of Aug 2026


def test_long_in_opex_window_negative_vanna(monkeypatch):
    _wire(monkeypatch, spot=772.0, net_vanna=-6e8)
    s = V().signal("SPY")
    assert s["action"] == "LONG" and s["biz_days_to_opex"] == 6 and s["opex"] == "2026-08-21"


def test_flat_when_vanna_positive(monkeypatch):
    _wire(monkeypatch, spot=772.0, net_vanna=+3e8)      # positive vanna -> no rally setup
    assert V().signal("SPY")["action"] == "FLAT"


def test_flat_outside_opex_window(monkeypatch):
    monkeypatch.setattr(V, "_today", staticmethod(lambda: date(2026, 8, 3)))   # ~14 biz days out
    _wire(monkeypatch, spot=772.0)
    assert V().signal("SPY")["action"] == "FLAT"


def test_opens_then_closes_at_opex(monkeypatch):
    _wire(monkeypatch, spot=772.0)
    assert V().mark()["opened"] == 1
    # jump to OPEX day, price up 1.5% -> close at expiry, a win
    monkeypatch.setattr(V, "_today", staticmethod(lambda: date(2026, 8, 21)))
    _wire(monkeypatch, spot=783.6)
    r = V().mark()
    assert r["closed"] == 1
    c = json.loads(V.CLOSED.read_text().splitlines()[-1])
    assert c["exit_reason"] == "opex" and c["net_return"] > 0


def test_stop_on_vol_spike(monkeypatch):
    _wire(monkeypatch, spot=772.0)
    V().mark()
    _wire(monkeypatch, spot=748.0)     # -3.1% > 2.5% stop -> bail (vol spike inverted the flow)
    V().mark()
    c = json.loads(V.CLOSED.read_text().splitlines()[-1])
    assert c["exit_reason"] == "stop" and c["net_return"] < 0


def test_report_gating(monkeypatch):
    _wire(monkeypatch, spot=772.0)
    assert V().report()["status"] == "VANNA_SHADOW_NO_DATA"
    V.CLOSED.write_text("\n".join(json.dumps({"net_return": 0.004}) for _ in range(V.MIN_CLOSED)) + "\n")
    rep = V().report()
    assert rep["status"] == "VANNA_SHADOW_MEASURING" and rep["closed_trades"] == V.MIN_CLOSED and rep["win_rate_pct"] == 100.0
