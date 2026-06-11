from datetime import datetime


class GreyLineStrategyRegimeEngine:

    def detect_regime(self, processed_state):

        total_pnl = processed_state.get("total_unrealized_pnl", 0)

        positions = processed_state.get("positions", [])
        avg_change = 0

        if positions:
            changes = []
            for p in positions:
                entry = p.get("entry_price", 0)
                current = p.get("current_price", entry)

                if entry > 0:
                    changes.append((current - entry) / entry * 100)

            avg_change = sum(changes) / len(changes) if changes else 0

        regime = "NEUTRAL"

        if avg_change > 1.5:
            regime = "TREND_UP"
        elif avg_change < -1.5:
            regime = "TREND_DOWN"
        elif abs(avg_change) < 0.5:
            regime = "CHOPPY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "avg_change_pct": round(avg_change, 4),
            "total_pnl": total_pnl,
            "regime": regime,
            "status": "REGIME_DETECTED"
        }
