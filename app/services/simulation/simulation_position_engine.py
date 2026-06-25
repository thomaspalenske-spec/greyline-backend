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
