class SimulationPositionEngine:
    """
    Tracks open simulated positions during walk-forward replay.

    First version:
    - Adds newly opened positions.
    - Marks unrealized P/L using current replay close.
    - Does not use future data.
    """

    def update(self, open_positions, execution, market_data):
        open_positions = list(open_positions or [])
        execution = execution or {}
        market_data = market_data or {}

        if execution.get("position_opened") is True:
            open_positions.append({
                "symbol": execution.get("symbol"),
                "direction": execution.get("direction"),
                "option_type": execution.get("option_type") or ("PUT" if execution.get("direction") == "BEARISH" else "CALL"),
                "composite_score": execution.get("composite_score"),
                "regime": execution.get("regime"),
                "regime_score": execution.get("regime_score"),
                "risk_state": execution.get("risk_state"),
                "risk_state_score": execution.get("risk_state_score"),
                "institutional_sponsorship_score": execution.get("institutional_sponsorship_score"),
                "institutional_inflow_score": execution.get("institutional_inflow_score"),
                "institutional_outflow_score": execution.get("institutional_outflow_score"),
                "net_institutional_flow_score": execution.get("net_institutional_flow_score"),
                "institutional_flow_direction": execution.get("institutional_flow_direction"),
                "institutional_flow_confidence": execution.get("institutional_flow_confidence"),
                "institutional_flow_reasons": execution.get("institutional_flow_reasons"),
                "footprint_confirmed_sponsorship": execution.get("footprint_confirmed_sponsorship"),
                "trend_persistence_score": execution.get("trend_persistence_score"),
                "breadth_score": execution.get("breadth_score"),
                "asymmetry_score": execution.get("asymmetry_score"),
                "volatility_score": execution.get("volatility_score"),
                "expected_value_score": execution.get("expected_value_score"),
                "direction_confidence": execution.get("direction_confidence"),
                "historical_execution_bonus": execution.get("historical_execution_bonus"),
                "bullish_score": execution.get("bullish_score"),
                "bearish_score": execution.get("bearish_score"),
                "setup_score": execution.get("setup_score"),
                "entry_time": execution.get("entry_time"),
                "entry_price": execution.get("entry_price"),
                "shares": execution.get("shares"),
                "capital_deployed": execution.get("capital_deployed"),
                "status": "OPEN",
            })

        current_close = self._num(market_data.get("close"))

        updated = []
        for pos in open_positions:
            entry = self._num(pos.get("entry_price"))
            shares = self._num(pos.get("shares"))

            unrealized_pnl = None
            unrealized_pnl_pct = None

            if current_close is not None and entry and shares:
                if pos.get("direction") == "BEARISH":
                    unrealized_pnl = (entry - current_close) * shares
                else:
                    unrealized_pnl = (current_close - entry) * shares

                base = entry * shares
                unrealized_pnl_pct = (unrealized_pnl / base) * 100 if base else None

            new_pos = dict(pos)
            new_pos["current_price"] = current_close
            new_pos["unrealized_pnl"] = round(unrealized_pnl, 2) if unrealized_pnl is not None else None
            new_pos["unrealized_pnl_pct"] = round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None
            new_pos["future_data_used"] = False
            updated.append(new_pos)

        return {
            "open_positions": updated,
            "open_position_count": len(updated),
            "future_data_used": False,
            "status": "SIMULATION_POSITION_UPDATE_READY",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
