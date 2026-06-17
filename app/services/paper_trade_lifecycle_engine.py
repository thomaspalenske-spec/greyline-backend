from datetime import datetime
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class PaperTradeLifecycleEngine:
    """
    Tracks simulated paper trade lifecycle events.
    Does not place live orders.
    """

    def entry(self, symbol="PLTR", side="BUY", quantity=1, entry_price=None):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLifecycleEngine",
            "lifecycle_event": "ENTRY",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "execution_mode": "PAPER_ONLY",
            "live_order_placement_attempted": False,
            "status": "PAPER_TRADE_ENTRY_RECORDED",
        }

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_ENTRY", event)
        event["audit_logged"] = True
        event["audit_result"] = audit
        return event

    def mark_to_market(self, symbol="PLTR", current_price=None):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLifecycleEngine",
            "lifecycle_event": "MARK_TO_MARKET",
            "symbol": symbol,
            "current_price": current_price,
            "execution_mode": "PAPER_ONLY",
            "live_order_placement_attempted": False,
            "status": "PAPER_TRADE_MARK_TO_MARKET_RECORDED",
        }

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_MARK_TO_MARKET", event)
        event["audit_logged"] = True
        event["audit_result"] = audit
        return event

    def exit(self, symbol="PLTR", exit_price=None, reason="MANUAL_SIMULATED_EXIT"):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLifecycleEngine",
            "lifecycle_event": "EXIT",
            "symbol": symbol,
            "exit_price": exit_price,
            "exit_reason": reason,
            "execution_mode": "PAPER_ONLY",
            "live_order_placement_attempted": False,
            "status": "PAPER_TRADE_EXIT_RECORDED",
        }

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_EXIT", event)
        event["audit_logged"] = True
        event["audit_result"] = audit
        return event
