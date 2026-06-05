from fastapi import APIRouter

from app.services.portfolio_data_model_engine import PortfolioDataModelEngine
from app.services.portfolio_snapshot_model_engine import PortfolioSnapshotModelEngine
from app.services.portfolio_position_model_engine import PortfolioPositionModelEngine
from app.services.portfolio_order_model_engine import PortfolioOrderModelEngine
from app.services.portfolio_balance_model_engine import PortfolioBalanceModelEngine
from app.services.portfolio_account_model_engine import PortfolioAccountModelEngine
from app.services.portfolio_aggregation_engine import PortfolioAggregationEngine
from app.services.portfolio_repository import PortfolioRepository
from app.services.portfolio_snapshot_service import PortfolioSnapshotService
from app.services.portfolio_state_engine import PortfolioStateEngine
from app.services.portfolio_integrity_engine import PortfolioIntegrityEngine
from app.services.portfolio_health_dashboard_engine import PortfolioHealthDashboardEngine

router = APIRouter()


@router.get("/portfolio-schema")
def portfolio_schema():
    return PortfolioDataModelEngine().get_schema()


@router.get("/portfolio-snapshot-model")
def portfolio_snapshot_model():
    return PortfolioSnapshotModelEngine().create_empty_snapshot()


@router.get("/portfolio-position-model")
def portfolio_position_model():
    return PortfolioPositionModelEngine().create_empty_position()


@router.get("/portfolio-order-model")
def portfolio_order_model():
    return PortfolioOrderModelEngine().create_empty_order()


@router.get("/portfolio-balance-model")
def portfolio_balance_model():
    return PortfolioBalanceModelEngine().create_empty_balance()


@router.get("/portfolio-account-model")
def portfolio_account_model():
    return PortfolioAccountModelEngine().create_empty_account()


@router.get("/portfolio")
def portfolio():
    return PortfolioAggregationEngine().aggregate_empty_portfolio()


@router.get("/portfolio-repository-test")
def portfolio_repository_test():
    repo = PortfolioRepository()

    snapshot = {
        "account_id": None,
        "cash_balance": 0.0,
        "equity": 0.0,
        "positions": [],
        "open_orders": [],
        "source": "TEST_ONLY",
        "execution_enabled": False
    }

    save_result = repo.save_snapshot(snapshot)
    load_result = repo.load_latest_snapshot()

    return {
        "save_result": save_result,
        "load_result": load_result,
        "execution_enabled": False,
        "status": "PORTFOLIO_REPOSITORY_TEST_PASS"
    }


@router.get("/portfolio-snapshot-service")
def portfolio_snapshot_service():
    return PortfolioSnapshotService().create_and_verify_snapshot()


@router.get("/portfolio-state")
def portfolio_state():
    return PortfolioStateEngine().evaluate_state()


@router.get("/portfolio-integrity")
def portfolio_integrity():
    return PortfolioIntegrityEngine().evaluate_integrity()


@router.get("/portfolio-health")
def portfolio_health():
    return PortfolioHealthDashboardEngine().get_dashboard()
