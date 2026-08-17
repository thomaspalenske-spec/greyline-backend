from fastapi import APIRouter

from app.services.options_exit_reconciler_engine import OptionsExitReconcilerEngine

router = APIRouter()


@router.get("/options-exit-quality")
def options_exit_quality():
    """Measured exit execution quality: realized fill price vs mid, and vs the old naked-market
    counterfactual (the bid). Proves whether pricing exits as limits actually pays."""
    return OptionsExitReconcilerEngine().status()


@router.post("/options-exit-reconcile")
def options_exit_reconcile():
    """Resolve any filled priced-exit orders now and append them to the measurement panel."""
    return OptionsExitReconcilerEngine().reconcile()
