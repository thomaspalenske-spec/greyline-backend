from fastapi import APIRouter

from app.services.shadow_comparison_engine import ShadowComparisonEngine

router = APIRouter()


@router.get("/shadow-comparison")
def shadow_comparison(horizon_hours: float = 24.0):
    return ShadowComparisonEngine(horizon_hours=horizon_hours).compare()
