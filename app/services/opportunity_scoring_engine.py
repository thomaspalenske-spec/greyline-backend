from datetime import datetime

from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.liquidity_scoring_engine import LiquidityScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine


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

            regime_score = RegimeScoringEngine().score_symbol(symbol).get("regime_score", 50)

            volatility_score = VolatilityScoringEngine().score_symbol(symbol).get("volatility_score", 50)

            expected_value_score = ExpectedValueScoringEngine().score_symbol(symbol).get("expected_value_score", 50)

            composite_score = round(
                (
                    market_data_score * 0.20
                    + liquidity_score * 0.18
                    + setup_score * 0.18
                    + regime_score * 0.16
                    + volatility_score * 0.13
                    + expected_value_score * 0.15
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
                "volatility_score": volatility_score,
                "expected_value_score": expected_value_score,
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
