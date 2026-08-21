"""FOMC-cycle equity-timing shadow — zero-capital forward test of the even-week premium (CMVJ 2019)."""

from fastapi import APIRouter

from app.services.fomc_cycle_shadow_engine import FomcCycleShadowEngine

router = APIRouter()


@router.get("/fomc-cycle-shadow")
def fomc_cycle_shadow():
    """Long the broad index in EVEN FOMC-cycle weeks / flat in odd, judged on the edge court's bar. Zero capital,
    no orders. Orthogonal to VRP; cheap equity; low turnover."""
    return FomcCycleShadowEngine().report()
