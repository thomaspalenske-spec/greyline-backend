from fastapi import APIRouter

from app.services.fixed_horizon_grader_engine import FixedHorizonGraderEngine

router = APIRouter()


@router.get("/fixed-horizon-validation")
def fixed_horizon_validation(horizon_hours: float = 24.0):
    result = FixedHorizonGraderEngine(horizon_hours=horizon_hours).grade()
    # Trim the per-decision detail for the API response; keep the summary.
    result.pop("graded", None)
    return result
