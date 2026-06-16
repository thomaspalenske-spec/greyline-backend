from fastapi import APIRouter

from app.services.paper_account_dashboard_engine import PaperAccountDashboardEngine

router = APIRouter()


@router.get("/paper-account-dashboard")
def paper_account_dashboard():
    return PaperAccountDashboardEngine().get_dashboard()
