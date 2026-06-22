from datetime import datetime


class BearMarketOpportunityEngine:
    def evaluate(self, opportunities=None):
        opportunities = opportunities or []

        bearish = []
        rejected = []

        for item in opportunities:
            directional_bias = str(item.get("directional_bias") or "").upper()
            option_type = str(item.get("option_type") or "").upper()

            if directional_bias == "BEARISH" or option_type == "PUT":
                bearish.append(item)
            else:
                rejected.append({
                    "symbol": item.get("symbol"),
                    "reason": "DIRECTIONAL_BIAS_NOT_BEARISH",
                    "directional_bias": item.get("directional_bias"),
                    "option_type": item.get("option_type"),
                    "result": item.get("result"),
                    "composite_score": item.get("composite_score"),
                    "bullish_score": item.get("bullish_score"),
                    "bearish_score": item.get("bearish_score"),
                })

        execute = [x for x in bearish if str(x.get("result", "")).upper() == "EXECUTE"]
        watch = [x for x in bearish if "WATCH" in str(x.get("result", "")).upper()]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BearMarketOpportunityEngine",
            "bearish_candidates": len(bearish),
            "bearish_execute": len(execute),
            "bearish_watch": len(watch),
            "best_bearish_candidate": sorted(
                bearish,
                key=lambda item: item.get("composite_score", 0),
                reverse=True
            )[0] if bearish else None,
            "bearish_rejection_audit_sample": rejected[:10],
            "status": "BEAR_MARKET_OPPORTUNITY_EVALUATED",
        }
