from fastapi import APIRouter

from app.services.price_bar_lineage_engine import PriceBarLineageEngine

router = APIRouter()


@router.get("/price-bar-lineage")
def price_bar_lineage(verify: bool = False, accept: bool = False):
    """Has settled price history changed since the accepted baseline? (reproducibility guard)
    ?verify=true runs a check now; ?accept=true re-accepts current data as the new baseline
    (only after reviewing a flagged change)."""
    eng = PriceBarLineageEngine()
    if accept:
        return eng.snapshot(force=True)
    if verify:
        return eng.verify()
    return {"baseline": eng.baseline_info(), "last_report": eng.last_report()}
