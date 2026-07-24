from fastapi import APIRouter

from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine

router = APIRouter()


@router.get("/conditional-vrp-panel")
def conditional_vrp_panel():
    """Out-of-sample forward test of the conditional-VRP candidate: entries recorded live, resolved
    ~30 days later, verdict on accumulated out-of-sample data only. INSUFFICIENT until powered."""
    return ConditionalVRPForwardPanelEngine().panel_status()


@router.post("/conditional-vrp-panel/record")
def conditional_vrp_panel_record():
    """Record today's rich-IV/non-earnings entries now (normally runs once/day in the scheduler)."""
    return ConditionalVRPForwardPanelEngine().record_signals()
