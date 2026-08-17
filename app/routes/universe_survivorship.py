from fastapi import APIRouter

from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine

router = APIRouter()


@router.get("/universe-survivorship")
def universe_survivorship(snapshot: bool = False):
    """Point-in-time universe coverage and retained delisted names.
    ?snapshot=true records today's membership now."""
    eng = UniverseSurvivorshipEngine()
    if snapshot:
        out = eng.snapshot()
        out["departures"] = eng.detect_departures()
        return out
    return eng.status()


@router.get("/survivorship-exposure")
def survivorship_exposure():
    """Per-STUDY survivorship exposure — a quantified statement per backtest instead of a blanket caveat.
    Classifies GreyLine's key studies: the confirmed index VRP (VIX/SPY) is survivorship-free BY
    CONSTRUCTION; single-name equity/momentum studies reach the pre-archive era and are biased UPWARD;
    the real-futures TSMOM window (2021+) is checked against the PIT archive."""
    eng = UniverseSurvivorshipEngine()
    studies = {}
    # confirmed edge — index level, clean by construction
    studies["index_vrp_24yr"] = eng.study_exposure(["SPY"], index_level=True)
    # single-name momentum universe (reaches pre-archive → biased upward)
    try:
        from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
        uni = list(MomentumReversalStrategyEngine()._symbols())[:50]
        studies["momentum_single_names"] = eng.study_exposure(uni)
    except Exception as e:
        studies["momentum_single_names"] = {"error": str(e)[:120]}
    # real-futures TSMOM (continuous @ROOT, 2021+ window)
    try:
        from app.services.alt_asset_universe_engine import AltAssetUniverseEngine
        studies["real_futures_tsmom"] = eng.study_exposure(
            AltAssetUniverseEngine.symbols(asset_class="futures"), since="2021-07-30")
    except Exception as e:
        studies["real_futures_tsmom"] = {"error": str(e)[:120]}
    return {"status": "SURVIVORSHIP_EXPOSURE_BY_STUDY", "studies": studies,
            "note": ("Index/ETF-level studies are survivorship-free by construction; single-name studies "
                     "reaching before the PIT archive are upper bounds (pre-archive failures unrecoverable). "
                     "See /universe-survivorship for the archive + delisted registry.")}
