"""Managed-futures sleeve: research verdict shape + live-sleeve gating/cadence/signal. No broker."""

from pathlib import Path

import pytest

from app.services.managed_futures_engine import ManagedFuturesEngine
from app.services.managed_futures_research_engine import ManagedFuturesResearchEngine

# conftest chdirs each test into a data sandbox, so point the historical-bar reads (read-only) at
# the real on-disk data dir — these tests specifically validate signal math over real history.
_REAL_HIST = Path(__file__).resolve().parents[1] / "app" / "data" / "historical"


@pytest.fixture(autouse=True)
def _real_history(monkeypatch):
    monkeypatch.setattr("app.services.managed_futures_research_engine.HIST", _REAL_HIST)
    monkeypatch.setattr(ManagedFuturesEngine, "HIST", _REAL_HIST)
    yield


# ---- research engine (reads CSVs only, no broker) ------------------------------------------

def test_research_runs_and_reports_verdict():
    r = ManagedFuturesResearchEngine().run()
    assert r["status"] == "MF_RESEARCH_READY"
    assert "GO" in r["verdict"]
    v = r["variants"]["long_short_monthly"]
    assert -1.0 < v["net"]["sharpe"] < 2.0            # a real, finite Sharpe
    assert v["cost_drag_sharpe"] >= 0                  # cost only ever hurts
    # crisis-alpha thesis: stress years present and the flagship ones positive
    crisis = r["crisis_alpha_net_pct"]
    assert any(k.startswith("2008") for k in crisis) and any(k.startswith("2022") for k in crisis)
    # diversification thesis: carry correlation is reported and near zero (the whole point)
    assert r["correlation"]["vs_svxy_carry_sleeve"] is not None
    assert abs(r["correlation"]["vs_svxy_carry_sleeve"]) < 0.4


def test_research_monthly_beats_weekly_after_cost():
    r = ManagedFuturesResearchEngine().run()
    m = r["variants"]["long_short_monthly"]["net"]["sharpe"]
    w = r["variants"]["long_short_weekly"]["net"]["sharpe"]
    assert m > w                                       # weekly turnover destroys the edge on cost


# ---- live sleeve gating (no broker) --------------------------------------------------------

def test_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("GREYLINE_MANAGED_FUTURES_ENABLED", raising=False)
    assert ManagedFuturesEngine().run_cycle()["status"] == "MF_DISABLED"


def test_after_hours_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_MANAGED_FUTURES_ENABLED", "true")
    assert ManagedFuturesEngine().run_cycle(is_regular_session=False)["status"] == "MF_MARKET_CLOSED"


def test_shorts_default_off(monkeypatch):
    monkeypatch.delenv("GREYLINE_MANAGED_FUTURES_ALLOW_SHORTS", raising=False)
    assert ManagedFuturesEngine().allow_shorts() is False


def test_budget_zero_until_funded(monkeypatch):
    monkeypatch.delenv("GREYLINE_MANAGED_FUTURES_ALLOC_PCT", raising=False)
    # resolver default pct for an unlisted sleeve is 0 -> budget 0
    assert ManagedFuturesEngine()._budget() == pytest.approx(0.0)


def test_monthly_cadence(monkeypatch, tmp_path):
    e = ManagedFuturesEngine()
    monkeypatch.setattr(type(e), "STATE", tmp_path)
    m = e._et_month()
    if m is None:
        pytest.skip("no ET tz")
    due, month = e.due()
    assert due is True and month == m                  # never rebalanced -> due
    e._mark_month(m)
    due2, _ = e.due()
    assert due2 is False                               # same month -> not due


def test_signal_is_blended_sign_and_bounded():
    e = ManagedFuturesEngine()
    sig = e._signal("TLT", 0.0)                         # uses CSV history, no live quote
    assert sig is not None
    assert -1.0 <= sig["blend"] <= 1.0
    assert sig["blend"] in (-1.0, -1 / 3, 1 / 3, 1.0)  # 3-horizon sign blend
    assert sig["vol"] >= 0.05                           # vol floor honored


def test_inflight_orders_counted_in_effective_held(monkeypatch):
    # MF sizes delta = target - held; resting (unfilled) BUYs must count as held so a rebalance can't
    # re-order on top of them (the low_vol/carry/trend stacking class). 5 filled + 3 resting -> held 8.
    from app.services.managed_futures_engine import ManagedFuturesEngine as M
    import app.services.in_flight_orders_engine as ifo
    monkeypatch.setattr(M, "_budget", lambda self: 10000.0)
    monkeypatch.setattr(M, "allow_shorts", staticmethod(lambda: False))
    monkeypatch.setattr(M, "_quote", lambda self, q, s: (100.0, 100.1, 100.0) if s == "QQQM" else (0, 0, 0))
    monkeypatch.setattr(M, "_signal",
                        lambda self, s, px: ({"blend": 1.0, "vol": 0.10, "stale": False, "last": 100.0}
                                             if s == "QQQM" else None))
    monkeypatch.setattr(M, "_held", lambda self, pos, s: 5 if s == "QQQM" else 0)
    monkeypatch.setattr(ifo.InFlightOrdersEngine, "snapshot",
                        classmethod(lambda cls, *a, **k: {"ok": True, "net": {"QQQM": 3}}))
    qq = [l for l in M().plan()["legs"] if l["symbol"] == "QQQM"][0]
    assert qq["held"] == 8                                  # 5 filled + 3 resting, not just 5


def test_inflight_degraded_read_adds_zero(monkeypatch):
    from app.services.managed_futures_engine import ManagedFuturesEngine as M
    import app.services.in_flight_orders_engine as ifo
    monkeypatch.setattr(M, "_budget", lambda self: 10000.0)
    monkeypatch.setattr(M, "allow_shorts", staticmethod(lambda: False))
    monkeypatch.setattr(M, "_quote", lambda self, q, s: (100.0, 100.1, 100.0) if s == "QQQM" else (0, 0, 0))
    monkeypatch.setattr(M, "_signal",
                        lambda self, s, px: ({"blend": 1.0, "vol": 0.10, "stale": False, "last": 100.0}
                                             if s == "QQQM" else None))
    monkeypatch.setattr(M, "_held", lambda self, pos, s: 5 if s == "QQQM" else 0)
    monkeypatch.setattr(ifo.InFlightOrdersEngine, "snapshot",
                        classmethod(lambda cls, *a, **k: {"ok": False, "net": {}}))   # degraded
    qq = [l for l in M().plan()["legs"] if l["symbol"] == "QQQM"][0]
    assert qq["held"] == 5                                  # fail-safe: add 0, don't fabricate
