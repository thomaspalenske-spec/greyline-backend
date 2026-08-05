"""Cross-sectional dual-momentum sleeve: ranks a cross-asset ETF universe by 12-1 return, holds the top
leaders that clear the absolute-momentum filter. Gated OFF; forward-test candidate. No broker calls."""

from datetime import datetime, timedelta

from app.services.cross_sectional_momentum_engine import CrossSectionalMomentumEngine as X


def test_rank_selects_top_n_and_applies_absolute_filter(monkeypatch):
    moms = {"QQQM": 0.30, "IWM": 0.20, "EFA": 0.10, "EEM": -0.05, "TLT": 0.02,
            "IEF": 0.01, "HYG": 0.03, "GLDM": 0.15, "DBC": -0.20, "VNQ": 0.08}
    monkeypatch.setattr(X, "_momentum", lambda self, s: moms.get(s))
    selected, allm = X()._rank()
    # top 4 by momentum, all with POSITIVE (absolute) momentum
    assert list(selected.keys()) == ["QQQM", "IWM", "GLDM", "EFA"]
    assert "EEM" not in selected and "DBC" not in selected      # negative momentum -> filtered out (dual mom)


def test_all_negative_momentum_selects_nothing(monkeypatch):
    # dual momentum crash guard: if nothing has positive absolute momentum, hold NOTHING (go to cash)
    monkeypatch.setattr(X, "_momentum", lambda self, s: -0.1)
    selected, _ = X()._rank()
    assert selected == {}


def test_momentum_is_none_on_insufficient_history(monkeypatch):
    monkeypatch.setattr(X, "_closes", lambda self, s: {"2026-01-01": 100.0})   # far too few bars
    assert X()._momentum("QQQM") is None


def test_momentum_computes_12_1_return(monkeypatch):
    x = X()
    n = X.LOOKBACK_DAYS + 30
    base = datetime.utcnow().date()
    closes = {(base - timedelta(days=(n - 1 - i))).isoformat(): 100.0 for i in range(n)}
    ds = sorted(closes)
    closes[ds[-(X.SKIP_DAYS + 1)]] = 120.0        # price ~1 month ago
    # price ~12 months ago stays 100 -> 12-1 return = 120/100 - 1 = 0.20
    monkeypatch.setattr(X, "_closes", lambda self, s: closes)
    m = x._momentum("QQQM")
    assert m is not None and abs(m - 0.20) < 1e-6


def test_stale_history_returns_none(monkeypatch):
    x = X()
    n = X.LOOKBACK_DAYS + 30
    base = datetime.utcnow().date() - timedelta(days=30)   # last bar 30 days old -> stale
    closes = {(base - timedelta(days=(n - 1 - i))).isoformat(): 100.0 for i in range(n)}
    monkeypatch.setattr(X, "_closes", lambda self, s: closes)
    assert x._momentum("QQQM") is None


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GREYLINE_XSMOM_ENABLED", raising=False)
    r = X().run_cycle()
    assert r["status"] == "XSMOM_DISABLED" and r["acted"] is False


def test_registered_in_edge_proof_and_budget():
    from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine
    from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
    assert "xs_momentum" in EdgeProofProtocolEngine.DEFAULTS
    assert "xs_momentum" in SleeveCapitalBudgetEngine.DEFAULT_PCT
