from fastapi import APIRouter

from app.services.options_entry_learning_engine import OptionsEntryLearningEngine
from app.services.options_entry_reconciler_engine import OptionsEntryReconcilerEngine

router = APIRouter()


@router.get("/options-entry-learning")
def options_entry_learning(limit: int = 20):
    """Phase 2 entry forecaster: current aggressiveness, fill-rate stats, and recent forecasts."""
    eng = OptionsEntryLearningEngine()
    outcomes = eng._read_outcomes()
    pending = [o for o in outcomes if o.get("status") == "PENDING"]
    return {
        "params": eng._load(),
        "stats": eng.stats(),
        "pending_count": len(pending),
        "recent": outcomes[-limit:],
        "explainer": ("aggressiveness 0=bid (cheapest, may not fill) .. 1=ask (fills like a "
                      "market order). Objective is COST, not fill rate: fill rate is a floor "
                      "(deploy enough capital); above it, aggressiveness is trimmed to pay less "
                      "spread. Settles at the cheapest entries that still clear the floor. "
                      "Improves as real fills accumulate."),
        "status": "OPTIONS_ENTRY_LEARNING_READY",
    }


@router.get("/options-entry-reconcile")
def options_entry_reconcile():
    """Force a fill reconciliation + refine pass now (normally runs each scheduler cycle)."""
    return OptionsEntryReconcilerEngine().reconcile()
