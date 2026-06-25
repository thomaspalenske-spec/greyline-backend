class SimulationExitEngine:
    """
    First-pass simulation exit engine.

    Rules:
    - Take profit at +2.0%
    - Stop loss at -1.0%
    - No future data used
    """

    def evaluate(self, open_positions, market_data):
        open_positions = list(open_positions or [])
        market_data = market_data or {}

        current_close = self._num(market_data.get("close"))
        remaining = []
        closed = []

        for pos in open_positions:
            pnl_pct = self._num(pos.get("unrealized_pnl_pct"))

            should_close = False
            exit_reason = None

            if pnl_pct is not None and pnl_pct >= 2.0:
                should_close = True
                exit_reason = "SIM_TAKE_PROFIT_2_PCT"
            elif pnl_pct is not None and pnl_pct <= -1.0:
                should_close = True
                exit_reason = "SIM_STOP_LOSS_1_PCT"

            if should_close:
                entry = self._num(pos.get("entry_price"))
                shares = self._num(pos.get("shares"))
                direction = pos.get("direction")

                realized_pnl = 0
                if current_close is not None and entry is not None and shares is not None:
                    realized_pnl = (current_close - entry) * shares
                    if direction == "BEARISH":
                        realized_pnl = (entry - current_close) * shares

                closed.append({
                    **pos,
                    "exit_price": current_close,
                    "realized_pnl": round(realized_pnl, 2),
                    "exit_reason": exit_reason,
                    "status": "CLOSED",
                    "future_data_used": False,
                })
            else:
                remaining.append(pos)

        return {
            "remaining_open_positions": remaining,
            "closed_positions": closed,
            "closed_count": len(closed),
            "future_data_used": False,
            "status": "SIMULATION_EXIT_EVALUATED",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
