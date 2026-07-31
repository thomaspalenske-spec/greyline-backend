"""Condor shadow forward-test — VRP/earnings condors built + marked off UW, no orders."""

from fastapi import APIRouter

from app.services.condor_shadow_engine import CondorShadowEngine
from app.services.best_condors_engine import BestCondorsEngine
from app.services.optionable_universe_engine import OptionableUniverseEngine
from app.services.decision_readout_engine import DecisionReadoutEngine

router = APIRouter()


@router.get("/condor-shadow")
def condor_shadow():
    """Hypothetical short-premium condor P&L (realized/unrealized), priced off Unusual Whales."""
    return CondorShadowEngine().report()


@router.get("/best-condors")
def best_condors(limit: int = 12):
    """Ranked list of buildable iron condors (VRP + earnings, off UW). Reads the scheduler's cache."""
    return BestCondorsEngine().cached(limit=limit)


@router.get("/optionable-universe")
def optionable_universe(limit: int = 300):
    """The VRP/condor universe DERIVED from live option open interest (not a hand-typed list).

    Reads the scheduler's monthly screen. Shows the rule, the ranked membership, and cache age."""
    return OptionableUniverseEngine().report(limit=limit)


@router.get("/decision-readout")
def decision_readout(condor_limit: int = 12):
    """The single sanctioned readout of what GreyLine has ACTUALLY decided — the same cached decisions
    the dashboard renders, aggregated and provenance-stamped (source, as_of, point-in-time). Nothing
    recomputed, so it matches the operator's screen. The canonical source for 'what will the system do'."""
    return DecisionReadoutEngine().readout(condor_limit=condor_limit)
