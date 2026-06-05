from fastapi import APIRouter

from app.services.trade_station_engine import TradeStationEngine
from app.services.tradestation_oauth_readiness_engine import TradeStationOAuthReadinessEngine
from app.services.tradestation_account_discovery_engine import TradeStationAccountDiscoveryEngine
from app.services.tradestation_read_only_client import TradeStationReadOnlyClient
from app.services.tradestation_endpoint_map_engine import TradeStationEndpointMapEngine
from app.services.tradestation_integration_dashboard_engine import TradeStationIntegrationDashboardEngine

router = APIRouter()


@router.get("/tradestation-status")
def tradestation_status():
    return TradeStationEngine().evaluate()


@router.get("/tradestation-oauth-readiness")
def tradestation_oauth_readiness():
    return TradeStationOAuthReadinessEngine().evaluate()


@router.get("/tradestation-account-discovery")
def tradestation_account_discovery():
    return TradeStationAccountDiscoveryEngine().evaluate()


@router.get("/tradestation-read-only-client")
def tradestation_read_only_client():
    return TradeStationReadOnlyClient().evaluate()


@router.get("/tradestation-endpoint-map")
def tradestation_endpoint_map():
    return TradeStationEndpointMapEngine().get_endpoint_map()


@router.get("/tradestation-dashboard")
def tradestation_dashboard():
    return TradeStationIntegrationDashboardEngine().get_dashboard()
