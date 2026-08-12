"""The alt-asset universe — long-vol ETPs, futures, spot FX added as tracked candidates with backfilled bars."""

from fastapi import APIRouter

from app.services.alt_asset_universe_engine import AltAssetUniverseEngine

router = APIRouter()


@router.get("/alt-asset-universe")
def alt_asset_universe(asset_class: str = None):
    """The 3 previously-untouched classes (vol_etp / futures / fx) registered with backfilled bars. vol ETPs
    are tradeable via existing equity execution; futures + spot FX are candidates that need their own
    execution plumbing before trading. Nothing here is armed."""
    if asset_class:
        return {"asset_class": asset_class, "symbols": AltAssetUniverseEngine.symbols(asset_class=asset_class),
                "status": "ALT_ASSET_UNIVERSE_CLASS"}
    return AltAssetUniverseEngine.snapshot()
