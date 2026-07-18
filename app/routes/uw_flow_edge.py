from fastapi import APIRouter

from app.services.uw_flow_grading_engine import UWFlowGradingEngine

router = APIRouter()


@router.get("/uw-flow-edge")
def uw_flow_edge():
    """Does Unusual Whales flow predict forward returns? Drift-robust, sample-honest. Measurement only."""
    return UWFlowGradingEngine().grade()
