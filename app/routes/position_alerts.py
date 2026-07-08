from datetime import datetime
from fastapi import APIRouter

router = APIRouter()


@router.get("/position-alerts")
def position_alerts():
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "alerts": [],
        "alert_count": 0,
        "status": "POSITION_ALERTS_READY",
    }
