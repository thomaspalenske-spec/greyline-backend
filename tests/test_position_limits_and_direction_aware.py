import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.position_exposure_limit_engine import PositionExposureLimitEngine
from app.services.risk_engine import entry_allowed

LIM = "app.services.position_exposure_limit_engine"


# ---- position/exposure limits ----
def _limits(open_count, sector_pct, env=None):
    env = env or {}

    def fake_getenv(key, default=None):
        return env.get(key, default)

    with patch(f"{LIM}.PortfolioExposureEngine") as MockExp, \
         patch(f"{LIM}.getenv", side_effect=fake_getenv):
        MockExp.return_value.evaluate.return_value = {
            "open_position_count": open_count,
            "max_sector_exposure_pct": sector_pct,
        }
        return PositionExposureLimitEngine().evaluate()


def test_limits_ok_under_thresholds():
    r = _limits(3, 20)
    assert r["limits_ok"] is True
    assert r["breaches"] == []


def test_max_open_positions_breach():
    r = _limits(10, 20)  # default max 10
    assert r["limits_ok"] is False
    assert any("MAX_OPEN_POSITIONS" in b for b in r["breaches"])


def test_max_sector_exposure_breach():
    r = _limits(3, 60)  # default max 50
    assert any("MAX_SECTOR_EXPOSURE_PCT" in b for b in r["breaches"])


def test_limits_env_configurable():
    r = _limits(4, 10, env={"GREYLINE_MAX_OPEN_POSITIONS": "3"})
    assert r["limits_ok"] is False


def test_limits_degrade_gracefully_on_error():
    with patch(f"{LIM}.PortfolioExposureEngine") as MockExp:
        MockExp.return_value.evaluate.side_effect = RuntimeError("boom")
        r = PositionExposureLimitEngine().evaluate()
    assert r["compute_ok"] is False
    assert r["breaches"] == []       # no fabricated breach
    # Fail CLOSED: this is a hard circuit breaker, so an unverifiable book (engine threw) must BLOCK
    # new concentration-gated risk rather than read as OK. (Was the fail-OPEN bug the audit flagged.)
    assert r["limits_ok"] is False


# ---- direction-aware entry_allowed ----
def _risk(hard=False, hard_factors=None, directional=False, net_bias="BULLISH", state="NORMAL"):
    return {
        "risk_state": state,
        "hard_block": hard,
        "hard_block_factors": hard_factors or [],
        "directional_soft_block": directional,
        "net_directional_bias": net_bias,
    }


def test_halted_blocks_all_directions():
    ok, _ = entry_allowed(_risk(state="HALTED"), "BEARISH")
    assert ok is False


def test_hard_block_blocks_all_directions():
    ok, reason = entry_allowed(_risk(hard=True, hard_factors=["CORRELATION_HIGH"], state="DEFENSIVE"), "BEARISH")
    assert ok is False
    assert "CORRELATION_HIGH" in reason


def test_directional_block_stops_same_direction():
    ok, _ = entry_allowed(_risk(directional=True, net_bias="BULLISH", state="DEFENSIVE"), "BULLISH")
    assert ok is False


def test_directional_block_allows_opposite_direction_to_rebalance():
    ok, reason = entry_allowed(_risk(directional=True, net_bias="BULLISH", state="DEFENSIVE"), "BEARISH")
    assert ok is True
    assert "rebalancing" in reason.lower()


def test_normal_allows_any_direction():
    assert entry_allowed(_risk(state="NORMAL"), "BULLISH")[0] is True
    assert entry_allowed(_risk(state="NORMAL"), "BEARISH")[0] is True
