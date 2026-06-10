from datetime import datetime

from app.services.paper_account_equity_engine import PaperAccountEquityEngine


class PaperAccountSnapshotEngine:

    def create_snapshot(
        self,
        cash_balance,
        positions
    ):
        equity = PaperAccountEquityEngine().calculate(
            cash_balance=cash_balance,
            positions=positions
        )

        return {
            "snapshot_timestamp": datetime.utcnow().isoformat(),
            "cash_balance": equity["cash_balance"],
            "market_value": equity["market_value"],
            "unrealized_pnl": equity["unrealized_pnl"],
            "equity": equity["equity"],
            "position_count": equity["position_count"],
            "status": "ACCOUNT_SNAPSHOT_CREATED"
        }
