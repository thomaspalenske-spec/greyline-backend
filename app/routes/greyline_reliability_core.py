from fastapi import APIRouter

from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine

router = APIRouter()


@router.get("/greyline-reliability-core")
def greyline_reliability_core():
    return GreyLineReliabilityCoreEngine().evaluate()
