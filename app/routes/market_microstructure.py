from fastapi import APIRouter

from app.services.market_microstructure_engine import MarketMicrostructureEngine

router = APIRouter()


@router.get("/market-microstructure")
def market_microstructure(
    bid_size: float = 1000,
    ask_size: float = 500,
    last: float = 100,
    open_price: float = 99,
    buy_volume: float = 10000,
    sell_volume: float = 7000,
    sweeps: float = 1,
    iceberg_probability: float = 50,
):
    quote = {
        "bid_size": bid_size,
        "ask_size": ask_size,
        "last": last,
        "open": open_price,
    }
    tape = {
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "sweeps": sweeps,
        "iceberg_probability": iceberg_probability,
    }
    return MarketMicrostructureEngine().evaluate(quote=quote, tape=tape)
