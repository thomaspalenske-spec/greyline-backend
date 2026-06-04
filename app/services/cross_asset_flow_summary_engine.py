from datetime import datetime

from app.services.cross_asset_flow_engine import CrossAssetFlowEngine


class CrossAssetFlowSummaryEngine:

    def summarize(self):
        flow = CrossAssetFlowEngine().evaluate_cross_asset_flow()
        rankings = flow.get("rankings", [])

        top_group = rankings[0] if rankings else None

        risk_on_groups = {"equities", "sector_etfs", "crypto_linked", "broad_market"}
        defensive_groups = {"futures_commodities"}

        top_group_name = top_group.get("asset_group") if top_group else None

        if top_group_name in risk_on_groups:
            market_bias = "RISK_ON_FLOW"
        elif top_group_name in defensive_groups:
            market_bias = "DEFENSIVE_OR_COMMODITY_FLOW"
        else:
            market_bias = "MIXED_FLOW"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "top_asset_group": top_group_name,
            "top_group_average_score": top_group.get("average_momentum_score") if top_group else None,
            "top_group_average_percent": top_group.get("average_momentum_percent") if top_group else None,
            "market_bias": market_bias,
            "execution_enabled": False,
            "status": "CROSS_ASSET_FLOW_SUMMARY_READY"
        }
