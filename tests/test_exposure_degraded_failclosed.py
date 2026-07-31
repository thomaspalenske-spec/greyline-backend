"""A degraded broker read must NOT let the concentration circuit-breaker read as OK.

The ETF sleeves (vol-carry / trend / managed-futures / T-bill) book straight to the broker and are
absent from the paper ledgers, so on a broker-read failure the real book is largely invisible. The
hard limit engine must fail CLOSED (block new concentration-gated risk) rather than compute a
falsely-clean, low concentration from the paper ledgers alone. No network — the broker view is
monkeypatched.
"""

import app.services.portfolio_exposure_engine as pee
from app.services.portfolio_exposure_engine import PortfolioExposureEngine
from app.services.position_exposure_limit_engine import PositionExposureLimitEngine


def _patch_broker(monkeypatch, snapshot):
    class _View:
        def snapshot(self_inner):
            return snapshot
    monkeypatch.setattr(pee, "BrokerAccountViewEngine", lambda: _View(), raising=False)


def test_exposure_flags_degraded_on_broker_read_failure(monkeypatch):
    # broker read failed → holdings unknown, not zero
    monkeypatch.setattr(PortfolioExposureEngine, "_broker_positions", lambda self: ([], True))
    out = PortfolioExposureEngine().evaluate()
    assert out["degraded"] is True and out["reads_ok"] is False
    assert out["status"] == "PORTFOLIO_EXPOSURE_DEGRADED"


def test_exposure_healthy_read_is_not_degraded(monkeypatch):
    monkeypatch.setattr(PortfolioExposureEngine, "_broker_positions", lambda self: ([], False))
    out = PortfolioExposureEngine().evaluate()
    assert out["degraded"] is False and out["reads_ok"] is True
    assert out["status"] == "PORTFOLIO_EXPOSURE_READY"


def test_limit_engine_fails_closed_when_exposure_degraded(monkeypatch):
    monkeypatch.setattr(
        PositionExposureLimitEngine, "evaluate", PositionExposureLimitEngine.evaluate
    )  # keep real evaluate
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 1, "max_sector_exposure_pct": 5.0, "degraded": True},
    )
    r = PositionExposureLimitEngine().evaluate()
    # unknown book must NOT read as OK — the hard breaker blocks new risk
    assert r["limits_ok"] is False
    assert r["compute_ok"] is False
    assert r["degraded"] is True
    assert r["status"] == "POSITION_LIMITS_DEGRADED"


def test_limit_engine_ok_only_when_confirmed_within_limits(monkeypatch):
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 1, "max_sector_exposure_pct": 5.0, "degraded": False},
    )
    r = PositionExposureLimitEngine().evaluate()
    assert r["limits_ok"] is True and r["compute_ok"] is True
    assert r["status"] == "POSITION_LIMITS_OK"
