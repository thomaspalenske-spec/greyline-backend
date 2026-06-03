from datetime import datetime


class TradeStationReadOnlyRequestGuard:

    ALLOWED_METHODS = ["GET"]

    ALLOWED_OPERATIONS = [
        "account_discovery",
        "account_balances",
        "positions",
        "orders"
    ]

    BLOCKED_OPERATIONS = [
        "order_placement",
        "order_replacement",
        "order_cancellation",
        "trade_execution"
    ]

    def evaluate_request(self, method, operation):
        method_allowed = method.upper() in self.ALLOWED_METHODS
        operation_allowed = operation in self.ALLOWED_OPERATIONS

        approved = method_allowed and operation_allowed

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "method": method.upper(),
            "operation": operation,
            "method_allowed": method_allowed,
            "operation_allowed": operation_allowed,
            "request_approved": approved,
            "execution_enabled": False,
            "status": "READ_ONLY_REQUEST_APPROVED" if approved else "REQUEST_BLOCKED"
        }
