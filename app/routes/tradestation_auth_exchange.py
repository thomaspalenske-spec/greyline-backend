from fastapi import APIRouter
from app.services.tradestation_auth_code_exchange_engine import (
    TradeStationAuthCodeExchangeEngine,
)

router = APIRouter()

@router.post("/tradestation-auth-exchange")
def tradestation_auth_exchange():
    return TradeStationAuthCodeExchangeEngine().exchange()
