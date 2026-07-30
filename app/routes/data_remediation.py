"""Data auto-remediation — status + manual trigger. Engine decides, route renders."""

from fastapi import APIRouter

from app.services.data_remediation_engine import DataRemediationEngine

router = APIRouter()


@router.get("/data-remediation")
def data_remediation():
    """Last remediation run + whether auto-remediation is armed."""
    return DataRemediationEngine().status()


@router.post("/data-remediation/run")
def data_remediation_run(apply: bool = False, universe_limit: int = 150, lineage: str = "auto"):
    """Manually run remediation. apply=false is a dry run. lineage: auto|force|never."""
    return DataRemediationEngine().remediate(apply=apply, universe_limit=universe_limit, lineage=lineage)
