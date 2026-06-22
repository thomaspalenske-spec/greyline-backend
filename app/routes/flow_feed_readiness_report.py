from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/flow-feed-readiness-report")
def flow_feed_readiness_report():
    feeds = {
        "unusual_options_flow": {
            "connected": False,
            "purpose": "Detect aggressive call/put premium, sweeps, blocks, and unusual contract demand.",
            "importance": "HIGH",
        },
        "dark_pool_prints": {
            "connected": False,
            "purpose": "Detect large off-exchange institutional equity transactions.",
            "importance": "HIGH",
        },
        "block_trade_surveillance": {
            "connected": False,
            "purpose": "Detect large institutional equity or option block activity.",
            "importance": "HIGH",
        },
        "dealer_gamma_exposure": {
            "connected": False,
            "purpose": "Estimate dealer hedging pressure and market pin/acceleration zones.",
            "importance": "HIGH",
        },
        "put_call_premium_flow": {
            "connected": False,
            "purpose": "Compare net bullish versus bearish option premium.",
            "importance": "HIGH",
        },
        "etf_creation_redemption_flow": {
            "connected": False,
            "purpose": "Detect sector/index capital entering or leaving ETFs.",
            "importance": "MEDIUM",
        },
        "sector_relative_volume_flow": {
            "connected": True,
            "purpose": "Infer rotation from live quote universe, volume, and relative strength.",
            "importance": "MEDIUM",
        },
        "institutional_sponsorship_score": {
            "connected": True,
            "purpose": "Infer institutional support from current GreyLine scoring engines.",
            "importance": "MEDIUM",
        },
    }

    connected = [name for name, item in feeds.items() if item.get("connected") is True]
    missing = [name for name, item in feeds.items() if item.get("connected") is False]
    high_priority_missing = [
        name for name, item in feeds.items()
        if item.get("connected") is False and item.get("importance") == "HIGH"
    ]

    direct_flow_ready = len(high_priority_missing) == 0

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "endpoint": "/flow-feed-readiness-report",
        "purpose": "Report whether GreyLine has direct institutional flow surveillance or only inferred flow.",
        "direct_institutional_flow_ready": direct_flow_ready,
        "current_flow_mode": "INFERRED_ONLY" if not direct_flow_ready else "DIRECT_AND_INFERRED",
        "connected_feed_count": len(connected),
        "missing_feed_count": len(missing),
        "high_priority_missing_count": len(high_priority_missing),
        "connected_feeds": connected,
        "missing_feeds": missing,
        "high_priority_missing_feeds": high_priority_missing,
        "feed_status": feeds,
        "readiness_judgment": "NOT_READY_FOR_TRUE_INSTITUTIONAL_FLOW_SURVEILLANCE" if not direct_flow_ready else "READY_FOR_TRUE_INSTITUTIONAL_FLOW_SURVEILLANCE",
        "status": "FLOW_FEED_READINESS_REPORT_READY",
    }
