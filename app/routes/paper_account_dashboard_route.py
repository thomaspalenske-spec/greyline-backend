from app.services.paper_account_dashboard_engine import PaperAccountDashboardEngine


def endpoint():
    return PaperAccountDashboardEngine().get_dashboard()
