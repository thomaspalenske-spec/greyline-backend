from datetime import datetime
import json


class LivePortfolioSnapshotNormalizer:

    def _parse_response(self, wrapper):
        response_json = wrapper.get("response_json")

        if isinstance(response_json, dict):
            return response_json

        preview = wrapper.get("response_preview", "")

        if not preview:
            return {}

        try:
            return json.loads(preview)
        except json.JSONDecodeError:
            return {}

    def normalize(self, snapshot):
        accounts_raw = self._parse_response(snapshot.get("accounts", {}))
        balances_raw = self._parse_response(
            snapshot.get("balances", {}).get("final_result", {})
        )
        positions_raw = self._parse_response(
            snapshot.get("positions", {}).get("final_result", {})
        )
        orders_raw = self._parse_response(snapshot.get("orders", {}))

        accounts = accounts_raw.get("Accounts", [])
        balances = balances_raw.get("Balances", [])
        positions = positions_raw.get("Positions", [])
        orders = orders_raw.get("Orders", [])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "snapshot_healthy": snapshot.get("snapshot_healthy", False),
            "account_count": len(accounts),
            "balance_count": len(balances),
            "position_count": len(positions),
            "order_count": len(orders),
            "accounts": accounts,
            "balances": balances,
            "positions": positions,
            "orders": orders,
            "execution_enabled": False,
            "status": "NORMALIZED_LIVE_PORTFOLIO_READY"
        }
