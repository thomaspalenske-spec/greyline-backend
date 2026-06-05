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


from app.services.tradestation_oauth_url_engine import TradeStationOAuthUrlEngine
from app.services.tradestation_token_exchange_readiness_engine import TradeStationTokenExchangeReadinessEngine
from app.services.tradestation_token_exchange_engine import TradeStationTokenExchangeEngine
from app.services.tradestation_account_discovery_live_engine import TradeStationAccountDiscoveryLiveEngine
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine
from app.services.tradestation_balance_retry_service import TradeStationBalanceRetryService
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.tradestation_positions_retry_service import TradeStationPositionsRetryService
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine


@router.get("/tradestation-oauth-url")
def tradestation_oauth_url():
    return TradeStationOAuthUrlEngine().generate_url()


@router.get("/tradestation-token-exchange-readiness")
def tradestation_token_exchange_readiness():
    return TradeStationTokenExchangeReadinessEngine().evaluate()


@router.get("/tradestation-token-exchange")
def tradestation_token_exchange():
    return TradeStationTokenExchangeEngine().exchange_code()


@router.get("/tradestation-account-discovery-live")
def tradestation_account_discovery_live():
    return TradeStationAccountDiscoveryLiveEngine().discover_accounts()


@router.get("/tradestation-balance-live")
def tradestation_balance_live():
    return TradeStationBalanceLiveEngine().get_balance()


@router.get("/tradestation-token-refresh")
def tradestation_token_refresh():
    return TradeStationTokenRefreshEngine().refresh_access_token()


@router.get("/tradestation-balance-retry")
def tradestation_balance_retry():
    return TradeStationBalanceRetryService().get_balance_with_refresh_retry()


@router.get("/tradestation-positions-live")
def tradestation_positions_live():
    return TradeStationPositionsLiveEngine().get_positions()


@router.get("/tradestation-positions-retry")
def tradestation_positions_retry():
    return TradeStationPositionsRetryService().get_positions_with_refresh_retry()


@router.get("/tradestation-orders-live")
def tradestation_orders_live():
    return TradeStationOrdersLiveEngine().get_orders()
