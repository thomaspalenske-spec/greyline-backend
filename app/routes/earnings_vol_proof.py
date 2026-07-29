"""Read-only scoreboard for the earnings implied-vs-realized edge — forward panel only."""

from fastapi import APIRouter

from app.services.earnings_vol_proof_engine import EarningsVolProofEngine

router = APIRouter()


@router.get("/earnings-vol-proof")
def earnings_vol_proof():
    """Does the options market overprice earnings moves? Mean implied-minus-realized spread as it
    resolves, split by IV-rank — honestly labelled underpowered until enough events accrue."""
    return EarningsVolProofEngine().status()
