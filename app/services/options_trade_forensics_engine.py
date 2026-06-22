from datetime import datetime


class OptionsTradeForensicsEngine:
    def analyze(self, trade):
        realized_pnl = float(trade.get("realized_pnl") or 0)
        realized_pnl_pct = float(trade.get("realized_pnl_pct") or 0)
        entry_price = float(trade.get("entry_price") or 0)
        exit_price = float(trade.get("exit_price") or trade.get("current_price") or 0)
        theta = float(trade.get("theta") or 0)
        delta = float(trade.get("delta") or 0)
        iv = float(trade.get("implied_volatility") or 0)
        exit_reason = trade.get("exit_reason")

        result = "WIN" if realized_pnl > 0 else "LOSS" if realized_pnl < 0 else "FLAT"

        stop_loss_triggered = str(exit_reason or "").upper().find("STOP_LOSS") >= 0
        severe_loss = realized_pnl_pct <= -30
        high_theta_drag = theta <= -0.10
        medium_delta = 0.25 <= abs(delta) <= 0.45
        high_iv = iv >= 0.35

        thesis_available = trade.get("entry_thesis_capture_status") == "ENTRY_THESIS_CAPTURED"

        if result == "WIN":
            grade = "A"
            largest_error = None
            lesson = "Trade closed profitably. Preserve setup pattern for comparison against future winners."
        elif stop_loss_triggered and high_theta_drag and high_iv:
            grade = "D"
            largest_error = "CONTRACT_SELECTION_OR_TIMING"
            lesson = "Option hit stop loss with meaningful theta drag and elevated implied volatility. Future reviews should test longer DTE, stronger delta, or stricter entry timing."
        elif stop_loss_triggered:
            grade = "D"
            largest_error = "STOP_LOSS_TRIGGERED"
            lesson = "Trade hit the configured options stop loss. Review whether stop distance, entry timing, or thesis quality caused the failure."
        elif severe_loss:
            grade = "D"
            largest_error = "DRAWDOWN_CONTROL"
            lesson = "Trade suffered a severe loss. Review whether the exit rule acted late or whether contract risk was too large."
        else:
            grade = "C"
            largest_error = "UNCLASSIFIED_LOSS"
            lesson = "Trade lost money, but more entry thesis data is needed to classify the failure precisely."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OptionsTradeForensicsEngine",
            "underlying": trade.get("underlying"),
            "option_symbol": trade.get("option_symbol"),
            "trade_result": result,
            "trade_grade": grade,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "stop_loss_triggered": stop_loss_triggered,
            "contract_diagnostics": {
                "delta": delta,
                "theta": theta,
                "implied_volatility": iv,
                "medium_delta": medium_delta,
                "high_theta_drag": high_theta_drag,
                "high_implied_volatility": high_iv,
                "expiration": trade.get("expiration") or trade.get("contract_expiration_date"),
            },
            "thesis_available": thesis_available,
            "entry_expected_value_score": trade.get("entry_expected_value_score"),
            "entry_regime_score": trade.get("entry_regime_score"),
            "entry_risk_state_score": trade.get("entry_risk_state_score"),
            "largest_error": largest_error,
            "lesson": lesson,
            "status": "OPTIONS_TRADE_FORENSICS_READY",
        }
