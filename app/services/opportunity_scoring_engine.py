from datetime import datetime

from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.liquidity_scoring_engine import LiquidityScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.trend_persistence_scoring_engine import TrendPersistenceScoringEngine
from app.services.breadth_scoring_engine import BreadthScoringEngine
from app.services.institutional_sponsorship_scoring_engine import InstitutionalSponsorshipScoringEngine
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine


class OpportunityScoringEngine:

    def score_opportunities(self):
        quote_scan = LiveUniverseQuoteScanner().scan_safe_subset()

        opportunities = []

        for item in quote_scan.get("symbols", []):
            symbol = item.get("symbol")
            quote_status = item.get("quote_status")
            http_status = item.get("http_status")

            market_data_score = 100 if http_status == 200 else 0
            liquidity_score = LiquidityScoringEngine().score_symbol(symbol).get('liquidity_score', 50)
            setup_score = SetupScoringEngine().score_symbol(symbol).get('setup_score', 50)

            regime_result = RegimeScoringEngine().score_symbol(symbol)
            regime_score = regime_result.get("regime_score", 50)

            volatility_score = VolatilityScoringEngine().score_symbol(symbol).get("volatility_score", 50)

            expected_value_score = ExpectedValueScoringEngine().score_symbol(symbol).get("expected_value_score", 50)

            trend_persistence_score = TrendPersistenceScoringEngine().score_symbol(symbol).get("trend_persistence_score", 50)

            breadth_score = BreadthScoringEngine().score_symbol(symbol).get("breadth_score", 50)

            institutional_sponsorship_score = InstitutionalSponsorshipScoringEngine().score_symbol(symbol).get("institutional_sponsorship_score", 50)

            asymmetry_score = AsymmetryScoringEngine().score_symbol(symbol).get("asymmetry_score", 50)

            risk_state_result = RiskStateScoringEngine().score_symbol(symbol)
            risk_state_score = risk_state_result.get("risk_state_score", 50)

            composite_score = round(
                (
                    market_data_score * 0.09
                    + liquidity_score * 0.12
                    + setup_score * 0.13
                    + regime_score * 0.10
                    + volatility_score * 0.08
                    + expected_value_score * 0.10
                    + trend_persistence_score * 0.08
                    + breadth_score * 0.07
                    + institutional_sponsorship_score * 0.06
                    + asymmetry_score * 0.09
                    + risk_state_score * 0.08
                ),
                2
            )

            if composite_score >= 85:
                result = "EXECUTE"
            elif composite_score >= 60:
                result = "WATCH"
            else:
                result = "REJECT"

            governor = ExecutionGovernor().evaluate_execution_permission(result)

            opportunities.append({
                "symbol": symbol,
                "quote_status": quote_status,
                "market_data_score": market_data_score,
                "liquidity_score": liquidity_score,
                "setup_score": setup_score,
                "regime_score": regime_score,
                "regime": regime_result.get("regime"),
                "regime_live_context": {
                    "last": regime_result.get("last"),
                    "previous_close": regime_result.get("previous_close"),
                    "vwap": regime_result.get("vwap"),
                    "net_change_pct": regime_result.get("net_change_pct"),
                    "volume": regime_result.get("volume"),
                    "previous_volume": regime_result.get("previous_volume"),
                },
                "volatility_score": volatility_score,
                "expected_value_score": expected_value_score,
                "trend_persistence_score": trend_persistence_score,
                "breadth_score": breadth_score,
                "institutional_sponsorship_score": institutional_sponsorship_score,
                "asymmetry_score": asymmetry_score,
                "risk_state_score": risk_state_score,
                "risk_state": risk_state_result.get("risk_state"),
                "risk_live_context": {
                    "last": risk_state_result.get("last"),
                    "bid": risk_state_result.get("bid"),
                    "ask": risk_state_result.get("ask"),
                    "spread_pct": risk_state_result.get("spread_pct"),
                    "vwap": risk_state_result.get("vwap"),
                    "vwap_distance_pct": risk_state_result.get("vwap_distance_pct"),
                    "net_change_pct_abs": risk_state_result.get("net_change_pct_abs"),
                    "volume": risk_state_result.get("volume"),
                    "previous_volume": risk_state_result.get("previous_volume"),
                },
                "composite_score": composite_score,
                "result": result,
                "order_placement_allowed": governor.get("order_placement_allowed"),
                "governor_status": governor.get("status"),
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scored": len(opportunities),
            "opportunities": opportunities,
            "execution_enabled": False,
            "status": "OPPORTUNITY_SCORING_COMPLETE"
        }
