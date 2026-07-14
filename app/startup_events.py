from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService


def register_startup_events(app):
    """Register background service auto-start handlers on the FastAPI app.

    Kept out of main.py so main.py stays bootstrap-only (routers + lifecycle wiring).
    """

    @app.on_event("startup")
    def auto_start_background_scheduler():
        BackgroundSchedulerService.start()

    @app.on_event("startup")
    def auto_start_fast_quote_heartbeat():
        FastQuoteHeartbeatService.start(
            symbols=["AMD", "NVDA"],
            interval_market_open_seconds=5,
            interval_market_closed_seconds=300,
        )
