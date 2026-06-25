from datetime import datetime

from app.services.institutional.feed_adapters.synthetic_adapter import SyntheticInstitutionalFeedAdapter
from app.services.institutional.feed_adapters.unusual_whales_adapter import UnusualWhalesAdapter
from app.services.institutional.feed_adapters.blackboxstocks_adapter import BlackBoxStocksAdapter
from app.services.institutional.feed_adapters.tradestation_adapter import TradeStationInstitutionalAdapter


class InstitutionalFeedAggregator:
    def __init__(self):
        self.adapters = [
            SyntheticInstitutionalFeedAdapter(),
            UnusualWhalesAdapter(),
            BlackBoxStocksAdapter(),
            TradeStationInstitutionalAdapter(),
        ]

    def evaluate(self, symbol=None):
        symbol = (symbol or "").upper().strip()
        provider_results = []

        for adapter in self.adapters:
            try:
                provider_results.append(adapter.evaluate(symbol))
            except Exception as e:
                provider_results.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "provider": getattr(adapter, "provider_name", "UNKNOWN"),
                    "feed_type": getattr(adapter, "feed_type", "UNKNOWN"),
                    "symbol": symbol,
                    "available": False,
                    "score": None,
                    "direction": "UNKNOWN",
                    "confidence": 0,
                    "events": [],
                    "error": str(e),
                    "status": "INSTITUTIONAL_FEED_ADAPTER_ERROR",
                })

        available = [r for r in provider_results if r.get("available") is True]
        scored = [r for r in available if r.get("score") is not None]

        if scored:
            avg_score = round(sum(float(r.get("score") or 0) for r in scored) / len(scored), 2)
            avg_confidence = round(sum(float(r.get("confidence") or 0) for r in scored) / len(scored), 2)
        else:
            avg_score = None
            avg_confidence = 0

        bullish_votes = len([r for r in available if r.get("direction") == "BULLISH"])
        bearish_votes = len([r for r in available if r.get("direction") == "BEARISH"])

        consensus_direction = (
            "BULLISH" if bullish_votes > bearish_votes
            else "BEARISH" if bearish_votes > bullish_votes
            else "UNKNOWN"
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "InstitutionalFeedAggregator",
            "symbol": symbol,
            "direct_feed_connected": any(
                r.get("available") is True and r.get("feed_type") != "SYNTHETIC_INFERENCE"
                for r in provider_results
            ),
            "provider_count": len(provider_results),
            "available_provider_count": len(available),
            "scored_provider_count": len(scored),
            "providers": [r.get("provider") for r in provider_results],
            "institutional_score": avg_score,
            "confidence": avg_confidence,
            "consensus_direction": consensus_direction,
            "bullish_votes": bullish_votes,
            "bearish_votes": bearish_votes,
            "provider_results": provider_results,
            "status": "INSTITUTIONAL_FEED_AGGREGATOR_READY",
        }
