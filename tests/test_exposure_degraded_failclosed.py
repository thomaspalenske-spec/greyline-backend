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


def _isolate_state(monkeypatch, tmp_path):
    """Point the last-good snapshot at a fresh tmp file so tests never see each other's writes."""
    monkeypatch.setattr(PositionExposureLimitEngine, "STATE_FILE", tmp_path / "exposure_last_good.json")


def _seed_last_good(tmp_path, open_count, sector_pct, age_s):
    from datetime import datetime, timedelta
    import json
    ts = (datetime.utcnow() - timedelta(seconds=age_s)).isoformat()
    (tmp_path / "exposure_last_good.json").write_text(json.dumps(
        {"timestamp": ts, "open_position_count": open_count, "max_sector_exposure_pct": sector_pct}))


def test_limit_engine_fails_closed_when_degraded_and_no_fresh_snapshot(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)                          # no snapshot on disk
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 1, "max_sector_exposure_pct": 5.0, "degraded": True},
    )
    r = PositionExposureLimitEngine().evaluate()
    # persistent degraded read, no fresh last-good → the hard breaker blocks new risk
    assert r["limits_ok"] is False
    assert r["compute_ok"] is False
    assert r["degraded"] is True
    assert r["status"] == "POSITION_LIMITS_DEGRADED"


def test_limit_engine_ok_only_when_confirmed_within_limits(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 1, "max_sector_exposure_pct": 5.0, "degraded": False},
    )
    r = PositionExposureLimitEngine().evaluate()
    assert r["limits_ok"] is True and r["compute_ok"] is True and r["source"] == "live"
    assert r["status"] == "POSITION_LIMITS_OK"
    # a confirmed-good read persists a snapshot for later transient-flap fallback
    assert (tmp_path / "exposure_last_good.json").exists()


def test_degraded_falls_back_to_fresh_last_good_within_limits(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _seed_last_good(tmp_path, open_count=3, sector_pct=20.0, age_s=120)   # fresh, well within limits
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 0, "max_sector_exposure_pct": 0.0, "degraded": True},
    )
    r = PositionExposureLimitEngine().evaluate()
    # transient flap → allowed on last-good, not blocked
    assert r["limits_ok"] is True and r["compute_ok"] is True
    assert r["source"] == "last_good" and r["status"] == "POSITION_LIMITS_OK_LAST_GOOD"
    assert r["open_position_count"] == 3 and r["last_good_age_s"] is not None


def test_degraded_stale_last_good_fails_closed(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _seed_last_good(tmp_path, open_count=3, sector_pct=20.0, age_s=5000)  # older than the 600s window
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 0, "max_sector_exposure_pct": 0.0, "degraded": True},
    )
    r = PositionExposureLimitEngine().evaluate()
    # persistent outage (stale snapshot) → still blocks
    assert r["limits_ok"] is False and r["compute_ok"] is False
    assert r["status"] == "POSITION_LIMITS_DEGRADED"


def test_degraded_fresh_last_good_at_limit_still_blocks(monkeypatch, tmp_path):
    _isolate_state(monkeypatch, tmp_path)
    _seed_last_good(tmp_path, open_count=10, sector_pct=20.0, age_s=60)   # fresh but AT max_open (10)
    monkeypatch.setattr(
        PortfolioExposureEngine, "evaluate",
        lambda self: {"open_position_count": 0, "max_sector_exposure_pct": 0.0, "degraded": True},
    )
    r = PositionExposureLimitEngine().evaluate()
    # last-good says the book was AT the limit → the breaker still blocks (safety preserved)
    assert r["limits_ok"] is False and r["breaches"]
    assert r["status"] == "POSITION_LIMITS_BREACHED"
