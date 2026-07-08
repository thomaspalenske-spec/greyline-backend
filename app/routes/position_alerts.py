from datetime import datetime
from fastapi import APIRouter

from app.services.options_stack_exposure_engine import OptionsStackExposureEngine

router = APIRouter()


@router.get("/position-alerts")
def position_alerts():
    alerts = []

    stack = OptionsStackExposureEngine().evaluate()

    for g in stack.get("stacked_groups", []):
        alerts.append({
            "severity": "WARNING",
            "category": "STACKED_OPTION_EXPOSURE",
            "title": f"{g.get('underlying')} {g.get('option_type')} stacked exposure",
            "message": f"{g.get('open_count')} open {g.get('underlying')} {g.get('option_type')} positions; cost ${g.get('total_cost')}; P/L ${g.get('total_pnl')}.",
            "underlying": g.get("underlying"),
            "option_type": g.get("option_type"),
            "open_count": g.get("open_count"),
            "total_cost": g.get("total_cost"),
            "total_pnl": g.get("total_pnl"),
            "positions": g.get("positions"),
        })

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "alerts": alerts,
        "alert_count": len(alerts),
        "status": "POSITION_ALERTS_READY",
    }
