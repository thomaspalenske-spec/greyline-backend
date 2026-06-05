from datetime import datetime

from app.services.live_portfolio_snapshot_repository import LivePortfolioSnapshotRepository


class LiveAccountDriftEngine:

    def _normalized(self, payload):
        return (
            payload.get("data", {})
            .get("snapshot", {})
            .get("normalized_snapshot", {})
        )

    def evaluate(self):
        repo = LivePortfolioSnapshotRepository()
        latest = repo.load_latest_snapshot()
        previous = repo.load_previous_snapshot()

        if latest.get("found") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "drift_checked": False,
                "drift_detected": None,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_LIVE_SNAPSHOT_AVAILABLE"
            }

        if previous.get("found") is not True:
            latest_normalized = self._normalized(latest)
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "drift_checked": False,
                "drift_detected": None,
                "snapshot_healthy": latest_normalized.get("snapshot_healthy", False),
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "NO_PREVIOUS_LIVE_SNAPSHOT_AVAILABLE"
            }

        latest_normalized = self._normalized(latest)
        previous_normalized = self._normalized(previous)

        drift_reasons = []

        fields = [
            ("account_count", "ACCOUNT_COUNT_CHANGED"),
            ("balance_count", "BALANCE_COUNT_CHANGED"),
            ("position_count", "POSITION_COUNT_CHANGED"),
            ("order_count", "ORDER_COUNT_CHANGED"),
        ]

        for field, reason in fields:
            if latest_normalized.get(field) != previous_normalized.get(field):
                drift_reasons.append(reason)

        latest_balance = (latest_normalized.get("balances") or [{}])[0]
        previous_balance = (previous_normalized.get("balances") or [{}])[0]

        balance_fields = [
            ("Equity", "EQUITY_CHANGED"),
            ("CashBalance", "CASH_BALANCE_CHANGED"),
            ("BuyingPower", "BUYING_POWER_CHANGED"),
            ("MarketValue", "MARKET_VALUE_CHANGED"),
        ]

        for field, reason in balance_fields:
            if latest_balance.get(field) != previous_balance.get(field):
                drift_reasons.append(reason)

        drift_detected = len(drift_reasons) > 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "drift_checked": True,
            "snapshot_healthy": latest_normalized.get("snapshot_healthy", False),
            "account_count": latest_normalized.get("account_count", 0),
            "balance_count": latest_normalized.get("balance_count", 0),
            "position_count": latest_normalized.get("position_count", 0),
            "order_count": latest_normalized.get("order_count", 0),
            "drift_detected": drift_detected,
            "drift_reasons": drift_reasons,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LIVE_ACCOUNT_DRIFT_DETECTED" if drift_detected else "LIVE_ACCOUNT_DRIFT_CLEAR"
        }
