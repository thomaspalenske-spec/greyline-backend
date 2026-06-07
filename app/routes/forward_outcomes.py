from fastapi import APIRouter
from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine

router = APIRouter()

@router.get("/forward-outcomes")
def forward_outcomes():
    return ForwardOutcomeCaptureEngine().capture()
