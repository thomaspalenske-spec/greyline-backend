from datetime import datetime

from app.services.historical_momentum_engine import HistoricalMomentumEngine


class CrossAssetFlowEngine:

    def evaluate_cross_asset_flow(self):
        groups = {
            "equities": ["NVDA", "AMD", "META", "AAPL", "MSFT", "AVGO", "AMZN", "PLTR", "TSM"],
            "sector_etfs": ["XLK", "SMH", "XLF", "XLE", "XLI", "XLV", "XLP", "XLU", "XLY", "XLB"],
            "crypto_linked": ["IBIT", "ETHE", "COIN", "MSTR"],
            "futures_commodities": ["ES", "NQ", "CL", "GC"],
            "broad_market": ["SPY", "QQQ", "IWM"]
        }

        results = []

        for group_name, symbols in groups.items():
            scores = []
            percents = []

            for symbol in symbols:
                momentum = HistoricalMomentumEngine().calculate_momentum(symbol)

                if momentum.get("momentum_available"):
                    scores.append(momentum.get("momentum_score", 0))
                    value = momentum.get("average_momentum_percent")
                    if value is not None:
                        percents.append(value)

            avg_score = round(sum(scores) / len(scores), 2) if scores else 0
            avg_percent = round(sum(percents) / len(percents), 4) if percents else None

            results.append({
                "asset_group": group_name,
                "symbols": symbols,
                "average_momentum_score": avg_score,
                "average_momentum_percent": avg_percent,
                "execution_enabled": False
            })

        results.sort(
            key=lambda item: item.get("average_momentum_score", 0),
            reverse=True
        )

        top_group = results[0]["asset_group"] if results else None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "groups_evaluated": len(results),
            "top_asset_group": top_group,
            "rankings": results,
            "execution_enabled": False,
            "status": "CROSS_ASSET_FLOW_READY"
        }
