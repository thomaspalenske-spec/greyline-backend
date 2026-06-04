from datetime import datetime

from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.liquidity_scoring_engine import LiquidityScoringEngine


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
            setup_score = 50

            composite_score = round(
                (
                    market_data_score * 0.4
                    + liquidity_score * 0.3
                    + setup_score * 0.3
                ),
                2
            )

            if composite_score >= 85:
                result = "EXECUTE"
            elif composite_score >= 60:
                result = "WATCH"
            else:
                result = "REJECT"

            opportunities.append({
                "symbol": symbol,
                "quote_status": quote_status,
                "market_data_score": market_data_score,
                "liquidity_score": liquidity_score,
                "setup_score": setup_score,
                "composite_score": composite_score,
                "result": result,
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scored": len(opportunities),
            "opportunities": opportunities,
            "execution_enabled": False,
            "status": "OPPORTUNITY_SCORING_COMPLETE"
        }
