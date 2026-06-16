from fastapi import APIRouter

from app.services.options_account_dashboard_engine import OptionsAccountDashboardEngine

router = APIRouter()


@router.get("/options-account-dashboard")
def options_account_dashboard():
    return OptionsAccountDashboardEngine().get_dashboard()
