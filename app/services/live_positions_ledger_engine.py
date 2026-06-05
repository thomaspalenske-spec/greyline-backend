from datetime import datetime

from app.services.live_portfolio_snapshot_builder import LivePortfolioSnapshotBuilder


class LivePositionsLedgerEngine:

    def get_positions_ledger(self):
        snapshot = LivePortfolioSnapshotBuilder().build_snapshot()
        normalized = snapshot.get("normalized_snapshot", {})
        positions = normalized.get("positions", [])

        ledger_positions = []

        for position in positions:
            ledger_positions.append({
                "source": "TRADESTATION_LIVE_READ_ONLY",
                "broker": "TradeStation",
                "account_id": position.get("AccountID"),
                "symbol": position.get("Symbol"),
                "asset_type": position.get("AssetType"),
                "quantity": position.get("Quantity"),
                "average_price": position.get("AveragePrice"),
                "market_value": position.get("MarketValue"),
                "unrealized_profit_loss": position.get("UnrealizedProfitLoss"),
                "execution_enabled": False,
                "status": "LIVE_POSITION_LEDGER_ADAPTED"
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_LIVE_READ_ONLY",
            "snapshot_healthy": normalized.get("snapshot_healthy", False),
            "position_count": len(ledger_positions),
            "positions": ledger_positions,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_POSITIONS_LEDGER_READY"
        }
