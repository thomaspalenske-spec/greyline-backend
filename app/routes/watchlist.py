from fastapi import APIRouter

from app.services.watchlist_engine import WatchlistEngine
from app.services.watchlist_reader import WatchlistReader
from app.services.watchlist_analytics_engine import WatchlistAnalyticsEngine
from app.services.watchlist_health_dashboard import WatchlistHealthDashboard
from app.services.watchlist_market_scanner import WatchlistMarketScanner

router = APIRouter()


@router.get("/watchlist")
def watchlist():
    return WatchlistEngine().get_watchlist()


@router.get("/watchlist-reader")
def watchlist_reader():
    return WatchlistReader().read_watchlist()


@router.get("/watchlist-analytics")
def watchlist_analytics():
    return WatchlistAnalyticsEngine().analyze_watchlist()


@router.get("/watchlist-health")
def watchlist_health():
    return WatchlistHealthDashboard().get_health()


@router.get("/watchlist-market-scan")
def watchlist_market_scan():
    return WatchlistMarketScanner().scan()
