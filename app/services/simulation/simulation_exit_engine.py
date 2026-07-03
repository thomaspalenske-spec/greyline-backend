from app.services.simulation.historical_exit_doctrine_engine import HistoricalExitDoctrineEngine


class SimulationExitEngine:
    """
    Simulator exit engine using GreyLine historical exit doctrine.
    No future data used.
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

            doctrine = HistoricalExitDoctrineEngine().build(
                symbol=pos.get("symbol"),
                signal=pos.get("entry_signal") or {},
                entry_price=self._num(pos.get("entry_price")),
                current_price=current_close,
                unrealized_pct=pnl_pct or 0,
            )

            stop_loss_pct = self._num(doctrine.get("stop_loss_pct"))
            take_profit_pct = self._num(doctrine.get("take_profit_pct"))

            if pnl_pct is not None and take_profit_pct is not None and pnl_pct >= take_profit_pct:
                should_close = True
                exit_reason = "GREYLINE_DYNAMIC_TAKE_PROFIT"
            elif pnl_pct is not None and stop_loss_pct is not None and pnl_pct <= stop_loss_pct:
                should_close = True
                exit_reason = "GREYLINE_DYNAMIC_STOP_LOSS"

            if should_close:
                entry = self._num(pos.get("entry_price"))
                shares = self._num(pos.get("shares"))
                direction = pos.get("direction")

                realized_pnl = 0
                if current_close is not None and entry is not None and shares is not None:
                    realized_pnl = (current_close - entry) * shares
                    if direction == "BEARISH":
                        realized_pnl = (entry - current_close) * shares

                capital_returned = self._num(pos.get("capital_deployed")) or 0

                entry_signal = pos.get("entry_signal") or {}

                closed.append({
                    **pos,
                    "option_type": pos.get("option_type") or entry_signal.get("option_type"),
                    "direction": pos.get("direction") or entry_signal.get("direction"),
                    "exit_price": current_close,
                    "realized_pnl": round(realized_pnl, 2),
                    "capital_returned": round(capital_returned, 2),
                    "total_cash_returned": round(capital_returned + realized_pnl, 2),
                    "capital_deployed_returned": round(capital_returned, 2),
                    "net_cash_returned": round(capital_returned + realized_pnl, 2),
                    "exit_reason": exit_reason,
                    "exit_doctrine": doctrine,
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
