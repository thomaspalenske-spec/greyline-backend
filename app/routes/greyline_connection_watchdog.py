from fastapi import APIRouter

from app.services.greyline_connection_watchdog_engine import GreyLineConnectionWatchdogEngine

router = APIRouter()

@router.get("/greyline-connection-watchdog")
def greyline_connection_watchdog():
    return GreyLineConnectionWatchdogEngine().run()
