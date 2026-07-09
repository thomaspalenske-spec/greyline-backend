from fastapi import APIRouter
from datetime import datetime
from pathlib import Path

from app.services.options_account_dashboard_engine import OptionsAccountDashboardEngine

router = APIRouter()


@router.get("/options-account-dashboard")
def options_account_dashboard():
    return OptionsAccountDashboardEngine().get_dashboard()


@router.post("/options-paper-trader-reset")
def options_paper_trader_reset():
    data_dir = Path("app/data/options_paper_trading")
    archive_dir = data_dir / "archive"
    ledger_file = data_dir / "options_paper_trade_ledger.jsonl"

    data_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archived_file = None

    if ledger_file.exists() and ledger_file.stat().st_size > 0:
        archived_file = archive_dir / f"options_paper_trade_ledger_reset_{timestamp}.jsonl"
        archived_file.write_text(ledger_file.read_text())

    ledger_file.write_text("")

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "reset": "OPTIONS_PAPER_TRADER_RESET",
        "starting_equity": 10000.0,
        "current_equity": 10000.0,
        "cash": 10000.0,
        "open_positions": 0,
        "closed_positions": 0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "archived_file": str(archived_file) if archived_file else None,
        "status": "OPTIONS_PAPER_TRADER_RESET_COMPLETE",
    }
