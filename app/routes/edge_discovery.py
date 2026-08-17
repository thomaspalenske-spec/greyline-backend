from fastapi import APIRouter

from app.services.edge_discovery_registry_engine import EdgeDiscoveryRegistryEngine
from app.services.earnings_vol_edge_engine import EarningsVolEdgeEngine

router = APIRouter()


@router.get("/edge-registry")
def edge_registry():
    """Every edge hypothesis ever tested and its verdict — nulls included, because a search
    that hides its failures lies about its successes. Includes the family-wise p threshold."""
    return EdgeDiscoveryRegistryEngine().status()


@router.get("/edge-magnitude-screen")
def edge_magnitude_screen(effect_pct: float = 1.0, leverage: float = 2.5,
                          horizon_days: int = None):
    """Screen 1: can an effect this large pay an option round-trip? For OPTIONS this matters
    more than significance — a 0.5% edge at p=0.0001 cannot clear a 500-1500bps toll."""
    return EdgeDiscoveryRegistryEngine().screen_magnitude(effect_pct, horizon_days, leverage)


@router.get("/earnings-vol-edge")
def earnings_vol_edge(record: bool = False):
    """Earnings implied-vs-realized move panel — the first candidate passing the magnitude
    screen. Forward-only: implied move cannot be reconstructed historically."""
    eng = EarningsVolEdgeEngine()
    if record:
        out = eng.record_implied()
        out["resolved"] = eng.resolve_realized().get("resolved")
        return out
    return eng.panel_status()
