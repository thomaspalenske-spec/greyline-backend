from fastapi import APIRouter

from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine

router = APIRouter()


@router.get("/paper-trading-command-center")
def paper_trading_command_center():
    engine = PaperTradingCommandCenterEngine()
    return engine.get_command_center()
