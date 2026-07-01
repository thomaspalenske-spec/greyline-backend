from fastapi import APIRouter, Query

from app.services.directional_attribution_report_engine import DirectionalAttributionReportEngine


router = APIRouter()


@router.get("/directional-attribution-report")
def directional_attribution_report(limit: int = Query(100, ge=1, le=500)):
    return DirectionalAttributionReportEngine().run(limit=limit)
