from datetime import datetime

from app.services.dynamic_divestment_engine import DynamicDivestmentEngine


class TPStateTrackingEngine:
    """
    Reporting-only TP state tracker.
    Does not place orders.
    Calculates hypothetical staged exits and remaining position.
    """

    def evaluate(self, trade):
        current = float(trade.get("current_price") or 0)
        entry = float(trade.get("entry_price") or 0)

        if entry <= 0 or current <= 0:
            return {
                "tp_state_engine": "UNAVAILABLE",
                "tp_state_status": "MISSING_PRICE_DATA",
            }

        qty = float(
            trade.get("quantity")
            or trade.get("contracts")
            or trade.get("original_position_size")
            or 0
        )

        if qty <= 0:
            return {
                "tp_state_engine": "UNAVAILABLE",
                "tp_state_status": "MISSING_POSITION_SIZE",
            }

        tp1 = float(trade.get("dynamic_tp1_price") or trade.get("tp1_price") or 0)
        tp2 = float(trade.get("dynamic_tp2_price") or trade.get("tp2_price") or 0)
        tp3 = float(trade.get("dynamic_tp3_price") or trade.get("tp3_price") or 0)

        tp1_hit = bool(tp1 and current >= tp1)
        tp2_hit = bool(tp2 and current >= tp2)
        tp3_hit = bool(tp3 and current >= tp3)

        divest_engine = DynamicDivestmentEngine()

        tp1_divestment = divest_engine.evaluate(trade, "TP1") if tp1_hit else None
        tp1_exit_qty = float((tp1_divestment or {}).get("recommended_exit_qty") or 0)
        remaining_after_tp1 = max(qty - tp1_exit_qty, 0)

        trade_tp2 = dict(trade)
        trade_tp2["position_remaining_after_tp_exits"] = remaining_after_tp1
        tp2_divestment = divest_engine.evaluate(trade_tp2, "TP2") if tp2_hit else None
        tp2_exit_qty = float((tp2_divestment or {}).get("recommended_exit_qty") or 0)
        tp2_exit_qty = min(tp2_exit_qty, remaining_after_tp1)
        remaining_after_tp2 = max(remaining_after_tp1 - tp2_exit_qty, 0)

        trade_tp3 = dict(trade)
        trade_tp3["position_remaining_after_tp_exits"] = remaining_after_tp2
        tp3_divestment = divest_engine.evaluate(trade_tp3, "TP3") if tp3_hit else None
        tp3_exit_qty = float((tp3_divestment or {}).get("recommended_exit_qty") or 0)
        tp3_exit_qty = min(tp3_exit_qty, remaining_after_tp2)

        total_exited = tp1_exit_qty + tp2_exit_qty + tp3_exit_qty
        remaining = max(qty - total_exited, 0)

        exit_unit = None

        runner_active = bool(tp3_hit and remaining > 0)

        if runner_active:
            stage = "RUNNER_ACTIVE"
            stop_state = "ATR_TRAILING_STOP_ACTIVE"
        elif tp2_hit:
            stage = "TP3_PENDING"
            stop_state = "LOCK_PROFIT_STOP"
        elif tp1_hit:
            stage = "TP2_PENDING"
            stop_state = "BREAKEVEN_STOP"
        else:
            stage = "TP1_PENDING"
            stop_state = "INITIAL_STOP_ACTIVE"

        return {
            "tp_state_engine": "ACTIVE",
            "tp_state_last_calculated_at": datetime.utcnow().isoformat(),
            "tp_state_reporting_only": True,

            "original_position_size": qty,
            "tp_exit_unit": exit_unit,
            "tp_exit_model": "DYNAMIC_DIVESTMENT_ADVISORY",
            "fixed_25pct_tp_exit_replaced": True,

            "tp1_state_hit": tp1_hit,
            "tp1_hypothetical_exit_qty": tp1_exit_qty,
            "tp1_hypothetical_exit_price": tp1 if tp1_hit else None,
            "tp1_dynamic_divestment": tp1_divestment,

            "tp2_state_hit": tp2_hit,
            "tp2_hypothetical_exit_qty": tp2_exit_qty,
            "tp2_hypothetical_exit_price": tp2 if tp2_hit else None,
            "tp2_dynamic_divestment": tp2_divestment,

            "tp3_state_hit": tp3_hit,
            "tp3_hypothetical_exit_qty": tp3_exit_qty,
            "tp3_hypothetical_exit_price": tp3 if tp3_hit else None,
            "tp3_dynamic_divestment": tp3_divestment,

            "total_hypothetical_exited_qty": total_exited,
            "position_remaining_after_tp_exits": remaining,
            "runner_position_size": remaining if runner_active else 0,
            "runner_active_by_tp_state": runner_active,

            "tp_state_stage": stage,
            "stop_escalation_state": stop_state,
            "live_partial_exit_enabled": False,
        }
