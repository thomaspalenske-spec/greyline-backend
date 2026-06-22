from fastapi import APIRouter

from app.services.market_battlefield_snapshot_cache import MarketBattlefieldSnapshotCache

router = APIRouter()


@router.post("/greyline-market-battlefield-cache/clear")
def clear_market_battlefield_cache():
    return MarketBattlefieldSnapshotCache.clear()
