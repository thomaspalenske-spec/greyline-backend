from fastapi import APIRouter

from app.services.operator_event_bus_engine import OperatorEventBusEngine
from app.services.operator_notification_engine import OperatorNotificationEngine

router = APIRouter()


@router.get("/operator-events")
def operator_events(limit: int = 50):
    return OperatorEventBusEngine().recent(limit=limit)


@router.get("/operator-notifications")
def operator_notifications():
    return OperatorNotificationEngine().unread()


@router.post("/operator-notifications/{notification_id}/ack")
def acknowledge_operator_notification(notification_id: str):
    return OperatorNotificationEngine().acknowledge(notification_id)


@router.post("/operator-notifications/ack-all")
def acknowledge_all_operator_notifications():
    return OperatorNotificationEngine().acknowledge_all()
