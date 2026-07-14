import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.risk_engine import RiskEngine

M = "app.services.risk_engine"


def _evaluate(max_dd=0.0, correlation="LOW", directional="LOW", env=None,
              drawdown_raises=False, correlation_raises=False):
    env = env or {}

    def fake_getenv(key, default=None):
        return env.get(key, default)

    with patch(f"{M}.PaperDrawdownEngine") as MDD, \
         patch(f"{M}.PortfolioCorrelationEngine") as MC, \
         patch(f"{M}.PortfolioDirectionalExposureEngine") as MDE, \
         patch(f"{M}.PositionExposureLimitEngine") as MLIM, \
         patch(f"{M}.getenv", side_effect=fake_getenv):
        if drawdown_raises:
            MDD.return_value.calculate.side_effect = RuntimeError("boom")
        else:
            MDD.return_value.calculate.return_value = {"max_drawdown_pct": max_dd, "peak_equity": 10000}
        if correlation_raises:
            MC.return_value.evaluate.side_effect = RuntimeError("boom")
        else:
            MC.return_value.evaluate.return_value = {"correlation_risk": correlation}
        MDE.return_value.evaluate.return_value = {"directional_risk": directional, "net_exposure_pct": 0}
        MLIM.return_value.evaluate.return_value = {"breaches": []}
        return RiskEngine().evaluate()


# ---- drawdown dimension (still real) ----
def test_normal_when_all_dimensions_low():
    r = _evaluate(max_dd=5.0, correlation="LOW", directional="LOW")
    assert r["risk_state"] == "NORMAL"
    assert r["blocking_factors"] == []


def test_defensive_on_drawdown_threshold():
    assert _evaluate(max_dd=12.0)["risk_state"] == "DEFENSIVE"


def test_halted_on_drawdown_halt():
    r = _evaluate(max_dd=25.0)
    assert r["risk_state"] == "HALTED"
    assert "DRAWDOWN_HALT" in r["blocking_factors"]


def test_thresholds_env_configurable():
    r = _evaluate(max_dd=6.0, env={"GREYLINE_RISK_DEFENSIVE_DRAWDOWN_PCT": "5"})
    assert r["risk_state"] == "DEFENSIVE"


# ---- correlation dimension (now real) ----
def test_defensive_on_high_correlation_even_with_low_drawdown():
    r = _evaluate(max_dd=1.0, correlation="HIGH")
    assert r["risk_state"] == "DEFENSIVE"
    assert "CORRELATION_HIGH" in r["blocking_factors"]
    assert r["risk_inputs"]["correlation"] == "LIVE_SECTOR_CLUSTER_CORRELATION"


def test_moderate_correlation_does_not_block():
    r = _evaluate(max_dd=1.0, correlation="MODERATE")
    assert r["risk_state"] == "NORMAL"


# ---- directional dimension (now real) ----
def test_defensive_on_high_directional_exposure():
    r = _evaluate(max_dd=1.0, directional="HIGH")
    assert r["risk_state"] == "DEFENSIVE"
    assert "DIRECTIONAL_EXPOSURE_HIGH" in r["blocking_factors"]


# ---- resilience: a dimension failure degrades, never crashes or halts ----
def test_drawdown_failure_degrades_non_blocking():
    r = _evaluate(drawdown_raises=True, correlation="LOW", directional="LOW")
    assert r["status"] == "RISK_STATE_DEGRADED"
    assert r["drawdown_state"] == "UNKNOWN"
    assert r["risk_state"] == "NORMAL"  # a telemetry failure does not block


def test_correlation_failure_degrades_non_blocking():
    r = _evaluate(max_dd=1.0, correlation_raises=True)
    assert r["risk_inputs"]["correlation"] == "DEGRADED_COMPUTE_FAILED"
    assert r["risk_state"] == "NORMAL"


# ---- liquidity remains an honest placeholder ----
def test_liquidity_labeled_placeholder():
    assert _evaluate()["risk_inputs"]["liquidity"] == "PLACEHOLDER_NOT_COMPUTED"


# ---- backward-compatible string accessor ----
def test_string_accessor():
    with patch(f"{M}.PaperDrawdownEngine") as MDD, \
         patch(f"{M}.PortfolioCorrelationEngine") as MC, \
         patch(f"{M}.PortfolioDirectionalExposureEngine") as MDE, \
         patch(f"{M}.PositionExposureLimitEngine") as MLIM:
        MDD.return_value.calculate.return_value = {"max_drawdown_pct": 25.0}
        MC.return_value.evaluate.return_value = {"correlation_risk": "LOW"}
        MDE.return_value.evaluate.return_value = {"directional_risk": "LOW"}
        MLIM.return_value.evaluate.return_value = {"breaches": []}
        assert RiskEngine().evaluate_risk_state() == "HALTED"


# ---- end-to-end: master decision blocks on a non-NORMAL risk state ----
def test_master_decision_blocks_on_risk_halt():
    import app.services.greyline_master_decision_engine as md

    with patch.object(md, "LiveBrokerHealthEngine") as MockBroker, \
         patch.object(md, "RiskEngine") as MockRisk, \
         patch.object(md, "OpportunitySummaryEngine") as MockOpp, \
         patch.object(md, "OpportunitySymmetryEngine"), \
         patch.object(md, "BearMarketOpportunityEngine"), \
         patch.object(md, "ExecutionGovernor") as MockGov, \
         patch.object(md, "ReliabilityGovernorEngine") as MockRel, \
         patch.object(md, "InstitutionalFlowEngine"), \
         patch.object(md, "ForecastOutcomeCaptureEngine"), \
         patch.object(md, "OperatorEventBusEngine") as MockBus, \
         patch.object(md, "MasterDecisionEventLog") as MockLog:
        MockBroker.return_value.evaluate.return_value = {"health_score": 100}
        MockRisk.return_value.evaluate.return_value = {"risk_state": "DEFENSIVE", "risk_inputs": {}}
        MockOpp.return_value.get_summary.return_value = {
            "opportunities": [{"result": "EXECUTE", "composite_score": 99, "symbol": "NVDA"}],
            "symbols_scored": 1,
        }
        MockGov.return_value.evaluate_execution_permission.return_value = {"order_placement_allowed": True}
        MockRel.return_value.evaluate.return_value = {"execution_allowed": True, "new_entries_allowed": True}
        MockBus.return_value.publish.return_value = {}
        MockLog.return_value.record_decision.return_value = {}
        result = md.GreyLineMasterDecisionEngine().evaluate()

    assert result["decision"] == "NO_ACTION"
    assert "Risk state does not allow execution" in result["decision_reason"]
