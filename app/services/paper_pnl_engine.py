from datetime import datetime


class PaperPnLEngine:

    def calculate(
        self,
        entry_price,
        current_price,
        quantity,
        side="BUY",
    ):
        # Direction-aware: a SHORT profits when price falls. This was long-only, which
        # silently inverts the sign on every short position.
        direction = -1 if str(side or "").upper() in ("SELL", "SELL_SHORT", "SHORT") else 1

        unrealized_pnl = (
            current_price - entry_price
        ) * quantity * direction

        unrealized_pct = (
            ((current_price / entry_price) - 1) * 100 * direction
            if entry_price > 0
            else 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "entry_price": entry_price,
            "current_price": current_price,
            "quantity": quantity,
            "side": side,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pct": round(unrealized_pct, 2),
            "status": "PAPER_PNL_CALCULATED"
        }
