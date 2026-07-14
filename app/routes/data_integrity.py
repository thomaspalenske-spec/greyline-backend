from fastapi import APIRouter

from app.services.data_integrity_engine import DataIntegrityEngine

router = APIRouter()


@router.get("/data-integrity")
def data_integrity():
    """Is the ground-truth data GreyLine learns from trustworthy? GREEN/AMBER/RED + why."""
    return DataIntegrityEngine().diagnose()
