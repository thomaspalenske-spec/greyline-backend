from fastapi import APIRouter
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine

router = APIRouter()

@router.get("/tradestation-token-maintenance")
def tradestation_token_maintenance():
    return TradeStationTokenMaintenanceEngine().evaluate()
