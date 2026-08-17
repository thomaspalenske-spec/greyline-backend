from fastapi import APIRouter

from app.services.cross_sectional_momentum_engine import CrossSectionalMomentumEngine

router = APIRouter()


@router.get("/cross-sectional-momentum")
def cross_sectional_momentum():
    """Cross-sectional (relative-strength) dual-momentum sleeve — ranks a broad cross-asset ETF universe
    by 12-1 return, holds the top leaders that clear the absolute-momentum filter. Read-only."""
    return CrossSectionalMomentumEngine().status()


@router.get("/cross-sectional-momentum-shadow")
def cross_sectional_momentum_shadow():
    """Shadow forward-test of the sleeve — hypothetical daily P&L on settled bars, NO orders (avoids the
    live sleeve-position collision). Read-only."""
    from app.services.cross_sectional_momentum_shadow_engine import CrossSectionalMomentumShadowEngine
    return CrossSectionalMomentumShadowEngine().report()
