"""GEX mean-reversion shadow: regime-aware fade signal + forward-test open/close (target/stop/regime-flip/
time) + report gating. GEX levels + spot stubbed — no network, no orders, temp state."""

import json

import pytest

from app.services.gex_mean_reversion_shadow_engine import GexMeanReversionShadowEngine as G


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "STATE", tmp_path)
    monkeypatch.setattr(G, "OPEN", tmp_path / "open.json")
    monkeypatch.setattr(G, "CLOSED", tmp_path / "closed.jsonl")
    monkeypatch.setattr(G, "NAMES", ["SPY"])
    monkeypatch.setattr(G, "MARK_MARKER", tmp_path / "last_mark.json")
    monkeypatch.setattr(G, "MARK_INTERVAL_MIN", 0)                        # no rate-gate in tests (mark on demand)
    monkeypatch.setattr(G, "_signals_cache", {"at": 0.0, "data": None})   # isolate the live-signal cache
    monkeypatch.setenv("GREYLINE_GEX_STRATEGY_SHADOW", "true")
    # Force the shadow-tradeability RTH gate OPEN so these open/settle tests are time-independent (the gate
    # itself is tested in test_shadow_tradeability_gate). Without this they fail whenever the suite runs after hours.
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)
    yield


# gamma_flip 500, magnet 505, call_wall 510, put_wall 490 — a long-gamma pin channel
_GEX = {"call_wall": 510.0, "gamma_flip": 500.0, "gamma_magnet": 505.0, "put_wall": 490.0}


def _wire(monkeypatch, spot, gex=_GEX):
    monkeypatch.setattr(G, "_gex_levels", lambda self, name, _g=gex: dict(_g))
    monkeypatch.setattr(G, "_spots", lambda self, names, _s=spot: {n: _s for n in names})


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_GEX_STRATEGY_SHADOW", "false")
    assert G().mark()["status"] == "GEX_SHADOW_DISABLED"


def test_flat_in_short_gamma(monkeypatch):
    _wire(monkeypatch, spot=495.0)     # below flip 500 -> short gamma -> stand aside
    s = G().signal("SPY")
    assert s["action"] == "FLAT" and s["regime"] == "short_gamma"


def test_short_at_call_wall(monkeypatch):
    _wire(monkeypatch, spot=511.0)     # long gamma (>flip), at/over call_wall 510, magnet 505 below -> SHORT
    s = G().signal("SPY")
    assert s["action"] == "SHORT" and s["target"] == 505.0 and s["stop"] > 510


# long-side channel: flip well below the put_wall so "spot at put_wall" is still LONG gamma (and the
# stop, put_wall*0.99, stays above the flip so it can't be mistaken for a regime flip)
_GEX_L = {"call_wall": 510.0, "gamma_flip": 470.0, "gamma_magnet": 505.0, "put_wall": 490.0}


def test_long_at_put_wall(monkeypatch):
    _wire(monkeypatch, spot=489.0, gex=_GEX_L)   # long gamma (>470), at/under put_wall 490, magnet 505 above
    s = G().signal("SPY")
    assert s["action"] == "LONG" and s["target"] == 505.0 and s["stop"] < 490


def test_flat_between_walls(monkeypatch):
    _wire(monkeypatch, spot=503.0)     # long gamma but mid-channel -> no edge
    assert G().signal("SPY")["action"] == "FLAT"


def test_open_then_close_at_target(monkeypatch):
    _wire(monkeypatch, spot=489.0, gex=_GEX_L)   # at put_wall in long gamma -> opens LONG @489
    assert G().mark()["opened"] == 1
    _wire(monkeypatch, spot=505.0, gex=_GEX_L)   # reverts up to the magnet -> TARGET win
    r = G().mark()
    assert r["closed"] == 1
    c = json.loads(G.CLOSED.read_text().splitlines()[-1])
    assert c["side"] == "LONG" and c["exit_reason"] == "target" and c["net_return"] > 0


def test_close_at_stop(monkeypatch):
    _wire(monkeypatch, spot=489.0, gex=_GEX_L)   # opens LONG @489, stop = 490*(1-0.01)=485.1 (above flip 470)
    G().mark()
    _wire(monkeypatch, spot=484.0, gex=_GEX_L)   # below stop but ABOVE flip -> STOP loss
    G().mark()
    c = json.loads(G.CLOSED.read_text().splitlines()[-1])
    assert c["exit_reason"] == "stop" and c["net_return"] < 0


def test_close_on_regime_flip(monkeypatch):
    _wire(monkeypatch, spot=489.0, gex=_GEX_L)   # opens LONG (flip 470)
    G().mark()
    _wire(monkeypatch, spot=469.0, gex=_GEX_L)   # now below flip 470 -> short gamma -> regime_flip exit
    G().mark()
    c = json.loads(G.CLOSED.read_text().splitlines()[-1])
    assert c["exit_reason"] == "regime_flip"


def test_report_gating(monkeypatch):
    _wire(monkeypatch, spot=503.0)
    assert G().report()["status"] == "GEX_SHADOW_NO_DATA"
    G.CLOSED.write_text("\n".join(json.dumps({"net_return": 0.002, "days_held": 3, "exit_reason": "target"})
                                  for _ in range(G.MIN_CLOSED)) + "\n")
    rep = G().report()
    assert rep["status"] == "GEX_SHADOW_MEASURING" and rep["closed_trades"] == G.MIN_CLOSED
    assert rep["win_rate_pct"] == 100.0
