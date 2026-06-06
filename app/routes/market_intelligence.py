from fastapi import APIRouter

from app.services.market_universe_engine import MarketUniverseEngine
from app.services.universe_quote_scanner import UniverseQuoteScanner
from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.opportunity_scoring_engine import OpportunityScoringEngine
from app.services.liquidity_scoring_engine import LiquidityScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.opportunity_summary_engine import OpportunitySummaryEngine
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.trend_persistence_scoring_engine import TrendPersistenceScoringEngine
from app.services.breadth_scoring_engine import BreadthScoringEngine
from app.services.institutional_sponsorship_scoring_engine import InstitutionalSponsorshipScoringEngine
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine

router = APIRouter()


@router.get("/market-universe")
def market_universe():
    return MarketUniverseEngine().get_universe()


@router.get("/universe-quote-scan")
def universe_quote_scan():
    return UniverseQuoteScanner().scan_universe()


@router.get("/live-universe-quote-scan")
def live_universe_quote_scan():
    return LiveUniverseQuoteScanner().scan_safe_subset()


@router.get("/opportunity-scores")
def opportunity_scores():
    return OpportunityScoringEngine().score_opportunities()


@router.get("/liquidity-score-nvda")
def liquidity_score_nvda():
    return LiquidityScoringEngine().score_symbol("NVDA")


@router.get("/setup-score-nvda")
def setup_score_nvda():
    return SetupScoringEngine().score_symbol("NVDA")


@router.get("/execution-governor-execute")
def execution_governor_execute():
    return ExecutionGovernor().evaluate_execution_permission("EXECUTE")


@router.get("/opportunity-summary")
def opportunity_summary():
    return OpportunitySummaryEngine().get_summary()


@router.get("/regime-score-nvda")
def regime_score_nvda():
    return RegimeScoringEngine().score_symbol("NVDA")


@router.get("/volatility-score-nvda")
def volatility_score_nvda():
    return VolatilityScoringEngine().score_symbol("NVDA")


@router.get("/expected-value-score-nvda")
def expected_value_score_nvda():
    return ExpectedValueScoringEngine().score_symbol("NVDA")


@router.get("/trend-persistence-score-nvda")
def trend_persistence_score_nvda():
    return TrendPersistenceScoringEngine().score_symbol("NVDA")


@router.get("/breadth-score-nvda")
def breadth_score_nvda():
    return BreadthScoringEngine().score_symbol("NVDA")


@router.get("/institutional-sponsorship-score-nvda")
def institutional_sponsorship_score_nvda():
    return InstitutionalSponsorshipScoringEngine().score_symbol("NVDA")


@router.get("/asymmetry-score-nvda")
def asymmetry_score_nvda():
    return AsymmetryScoringEngine().score_symbol("NVDA")


@router.get("/risk-state-score-nvda")
def risk_state_score_nvda():
    return RiskStateScoringEngine().score_symbol("NVDA")

from app.services.greyline_intelligence_dashboard_engine import GreyLineIntelligenceDashboardEngine


@router.get("/greyline-intelligence-dashboard")
def greyline_intelligence_dashboard():
    return GreyLineIntelligenceDashboardEngine().get_dashboard()

from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine


@router.get("/greyline-master-decision")
def greyline_master_decision():
    return GreyLineMasterDecisionEngine().evaluate()

from app.services.master_decision_history_engine import MasterDecisionHistoryEngine


@router.get("/master-decision-history")
def master_decision_history():
    return MasterDecisionHistoryEngine().get_history()
