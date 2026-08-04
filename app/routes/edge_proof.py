from fastapi import APIRouter

from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine

router = APIRouter()


@router.get("/edge-proof-protocol")
def edge_proof_protocol():
    """Pre-registered edge-proof verdicts. The per-sleeve hypothesis + required N + decision threshold +
    kill-rule are FROZEN before the data; PROVEN/RETIRE are BINDING at n>=required_n. Statistics come from
    the fill-truthful court — this layer only enforces the pre-committed decision. Bootstraps the frozen
    defaults on first read (idempotent; never overwrites an existing registration)."""
    eng = EdgeProofProtocolEngine()
    eng.bootstrap()
    return eng.evaluate()


@router.get("/condor-cost-screen")
def condor_cost_screen(half_spread_per_share: float = 0.03, commission_per_contract: float = 0.65):
    """Dead-on-arrival cost screen for the LIVE condors: a defined-risk condor already needs a 67-75%
    win-rate to break even; round-trip costs raise that. Flags condors whose cost drag exceeds the thin
    excess win-rate the VRP plausibly supplies. STATED cost model (no live NBBO); tune via query params."""
    return EdgeProofProtocolEngine().condor_cost_screen(
        half_spread_per_share=half_spread_per_share, commission_per_contract=commission_per_contract)
