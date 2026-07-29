"""Read-only proof scoreboard for the variance-premium harvest — realized trades only."""

from fastapi import APIRouter

from app.services.harvest_proof_engine import HarvestProofEngine

router = APIRouter()


@router.get("/harvest-proof")
def harvest_proof():
    """Did the harvest pay? Realized P&L, win rate, credit capture, and the adaptive-vs-static /
    rich-IV splits — honestly labelled underpowered until enough closed trades accrue."""
    return HarvestProofEngine().status()
