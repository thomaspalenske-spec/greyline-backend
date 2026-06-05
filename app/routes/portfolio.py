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


from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder
from app.services.live_portfolio_snapshot_persistence_service import LivePortfolioSnapshotPersistenceService
from app.services.live_portfolio_health_dashboard_service import LivePortfolioHealthDashboardService
from app.services.portfolio_equity_timeline_engine import PortfolioEquityTimelineEngine
from app.services.portfolio_equity_timeline_reader import PortfolioEquityTimelineReader
from app.services.portfolio_analytics_engine import PortfolioAnalyticsEngine
from app.services.portfolio_analytics_persistence_service import PortfolioAnalyticsPersistenceService
from app.services.portfolio_analytics_reader import PortfolioAnalyticsReader
from app.services.portfolio_dashboard_service import PortfolioDashboardService
from app.services.portfolio_summary_engine import PortfolioSummaryEngine
from app.services.portfolio_alert_engine import PortfolioAlertEngine


@router.get("/live-portfolio-snapshot")
def live_portfolio_snapshot():
    return LivePortfolioSnapshotBuilder().build_snapshot()


@router.get("/live-portfolio-snapshot-persist")
def live_portfolio_snapshot_persist():
    return LivePortfolioSnapshotPersistenceService().save_and_verify_live_snapshot()


@router.get("/live-portfolio-health")
def live_portfolio_health():
    return LivePortfolioHealthDashboardService().get_health_status()


@router.get("/portfolio-equity-timeline-record")
def portfolio_equity_timeline_record():
    return PortfolioEquityTimelineEngine().record_equity_point()


@router.get("/portfolio-equity-timeline")
def portfolio_equity_timeline():
    return PortfolioEquityTimelineReader().read_timeline()


@router.get("/portfolio-analytics")
def portfolio_analytics():
    return PortfolioAnalyticsEngine().analyze()


@router.get("/portfolio-analytics-persist")
def portfolio_analytics_persist():
    return PortfolioAnalyticsPersistenceService().save_and_verify_analytics()


@router.get("/portfolio-analytics-reader")
def portfolio_analytics_reader():
    return PortfolioAnalyticsReader().read_latest()


@router.get("/portfolio-dashboard")
def portfolio_dashboard():
    return PortfolioDashboardService().get_dashboard()


@router.get("/portfolio-summary")
def portfolio_summary():
    return PortfolioSummaryEngine().get_summary()


@router.get("/portfolio-alerts")
def portfolio_alerts():
    return PortfolioAlertEngine().evaluate_alerts()


from app.services.live_account_engine import LiveAccountEngine


@router.get("/account-live")
def account_live():
    return LiveAccountEngine().get_account()

from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine


@router.get("/live-broker-summary")
def live_broker_summary():
    return LiveBrokerSummaryEngine().summarize()

from app.services.live_broker_health_engine import LiveBrokerHealthEngine


@router.get("/live-broker-health")
def live_broker_health():
    return LiveBrokerHealthEngine().evaluate()

from app.services.live_dashboard_engine import LiveDashboardEngine


@router.get("/live-dashboard")
def live_dashboard():
    return LiveDashboardEngine().get_dashboard()

from app.services.live_account_drift_engine import LiveAccountDriftEngine


@router.get("/live-account-drift")
def live_account_drift():
    return LiveAccountDriftEngine().evaluate()

from app.services.live_monitoring_cycle_engine import LiveMonitoringCycleEngine


@router.get("/live-monitoring-cycle")
def live_monitoring_cycle():
    return LiveMonitoringCycleEngine().run_cycle()
