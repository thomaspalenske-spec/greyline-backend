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


@router.post("/operator-notifications/ack/{notification_id}")
def acknowledge_operator_notification_by_id(notification_id: str):
    return OperatorNotificationEngine().acknowledge(notification_id)


@router.post("/operator-events/test")
def operator_events_test():
    return OperatorEventBusEngine().publish(
        source="MANUAL_TEST",
        category="SYSTEM_TEST",
        severity="WARNING",
        title="Operator Event Bus Test",
        message="Manual operator event bus test notification.",
        ack_required=True,
        payload={"test": True},
    )
