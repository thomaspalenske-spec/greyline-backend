from datetime import datetime

from app.models.trade_model import create_trade
from app.services.execution_request_validator_engine import ExecutionRequestValidatorEngine
from app.services.execution_authorization_gate_engine import ExecutionAuthorizationGateEngine
from app.services.ledger_engine import LedgerEngine


class PaperTradeExecutionEngine:

    def execute(
        self,
        symbol,
        quantity,
        order_type,
        entry_price,
        governance_dashboard
    ):
        request_validation = ExecutionRequestValidatorEngine().validate(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type
        )

        if request_validation.get("valid") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "paper_trade_executed": False,
                "reason": "EXECUTION_REQUEST_INVALID",
                "request_validation": request_validation,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "PAPER_TRADE_REJECTED"
            }

        authorization = ExecutionAuthorizationGateEngine().authorize(
            governance_dashboard,
            requested_mode="paper"
        )

        if authorization.get("execution_authorized") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "paper_trade_executed": False,
                "reason": "EXECUTION_NOT_AUTHORIZED",
                "authorization": authorization,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "PAPER_TRADE_REJECTED"
            }

        trade = create_trade(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            state="ACTIVE",
            origin="PAPER_TRADE_EXECUTION",
            confidence="PAPER"
        )

        trade["order_type"] = order_type

        ledger_result = LedgerEngine().add_trade(trade)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trade_executed": ledger_result.get("trade_saved") is True,
            "trade_id": trade.get("trade_id"),
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "entry_price": entry_price,
            "request_validation": request_validation,
            "authorization": authorization,
            "ledger_result": ledger_result,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "PAPER_TRADE_EXECUTED" if ledger_result.get("trade_saved") is True else "PAPER_TRADE_REJECTED"
        }
