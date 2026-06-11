from datetime import datetime


class GreyLineStrategyEngine:

    def generate_signal(self, processed_market_state):

        positions = processed_market_state.get("positions", [])

        signals = []

        for pos in positions:

            pnl = pos.get("unrealized_pnl", 0)
            price = pos.get("current_price", 0)
            entry = pos.get("entry_price", 0)

            change_pct = 0
            if entry > 0:
                change_pct = ((price - entry) / entry) * 100

            signal = "HOLD"

            # Simple regime logic (baseline intelligence layer)
            if change_pct > 1.5:
                signal = "TAKE_PROFIT"
            elif change_pct < -1.0:
                signal = "CUT_LOSS"
            elif pnl > 0:
                signal = "HOLD_WINNER"
            else:
                signal = "HOLD_LOSER"

            signals.append({
                "symbol": pos.get("symbol"),
                "signal": signal,
                "change_pct": round(change_pct, 2),
                "unrealized_pnl": pnl
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "signals": signals,
            "status": "STRATEGY_SIGNAL_GENERATED"
        }
