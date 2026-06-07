from fastapi import APIRouter
from app.services.tradestation_auth_url_engine import TradeStationAuthUrlEngine

router = APIRouter()

@router.get("/tradestation-auth-url")
def tradestation_auth_url():
    return TradeStationAuthUrlEngine().generate()
