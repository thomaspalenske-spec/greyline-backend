from fastapi import APIRouter

from app.services.ops_metrics_engine import OpsMetricsEngine

router = APIRouter()


@router.get("/ops/metrics")
def ops_metrics():
    return OpsMetricsEngine().collect()
