from fastapi import APIRouter

from app.services.position_alert_ack_engine import PositionAlertAckEngine

router = APIRouter()


@router.get("/position-alerts")
def position_alerts():
    return PositionAlertAckEngine().unacknowledged_alerts()


@router.post("/position-alerts/ack/{trade_id}")
def acknowledge_position_alert(trade_id: str):
    return PositionAlertAckEngine().acknowledge(trade_id)
