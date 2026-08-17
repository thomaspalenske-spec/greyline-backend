from fastapi import APIRouter

from app.services.survivorship_bias_engine import SurvivorshipBiasEngine

router = APIRouter()


@router.get("/survivorship-bias")
def survivorship_bias(refresh: bool = False):
    """Quantified survivorship bias in the historical universe (disappearance rate from UW's
    delisting feed). The raw rate is an UPPER BOUND on missing names, not the return bias —
    see the interpretation block. ?refresh=true recomputes."""
    eng = SurvivorshipBiasEngine()
    return eng.assess() if refresh else (eng.last_report() or eng.assess())
