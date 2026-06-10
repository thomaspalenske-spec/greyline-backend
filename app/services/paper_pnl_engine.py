from datetime import datetime


class PaperPnLEngine:

    def calculate(
        self,
        entry_price,
        current_price,
        quantity
    ):
        unrealized_pnl = (
            current_price - entry_price
        ) * quantity

        unrealized_pct = (
            ((current_price / entry_price) - 1) * 100
            if entry_price > 0
            else 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "entry_price": entry_price,
            "current_price": current_price,
            "quantity": quantity,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pct": round(unrealized_pct, 2),
            "status": "PAPER_PNL_CALCULATED"
        }
