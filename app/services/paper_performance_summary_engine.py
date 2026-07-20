from datetime import datetime

from app.services.paper_drawdown_engine import PaperDrawdownEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


class PaperPerformanceSummaryEngine:

    @staticmethod
    def _mark_open_positions(open_trades):
        """(unrealized_pnl, unvalued_symbols) marking open trades to the last known price.

        Prices come from PriceHistoryStore, which is the forward feed the graders already
        rely on. A position whose symbol has no recorded price is reported as UNVALUED
        rather than silently marked flat.
        """
        if not open_trades:
            return 0.0, []

        from app.services.price_history_store import PriceHistoryStore

        store = PriceHistoryStore()
        total, unvalued = 0.0, []
        for trade in open_trades:
            symbol = trade.get("symbol")
            try:
                entry = float(trade.get("entry_price") or 0)
                qty = float(trade.get("quantity") or 0)
            except (TypeError, ValueError):
                entry, qty = 0.0, 0.0
            points = store._load(symbol) if symbol else []
            if entry <= 0 or qty <= 0 or not points:
                unvalued.append(symbol)
                continue
            last = points[-1][1]
            # SELL/short positions profit when price falls.
            sign = -1 if str(trade.get("side", "")).upper() in ("SELL", "SELL_SHORT", "SELLSHORT") else 1
            total += sign * (last - entry) * qty
        return round(total, 2), unvalued

    def summarize(self):
        starting_equity = 10000.0

        ledger = PaperTradeLedgerEngine().history()
        trades = ledger.get("trades", [])

        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
        symbols = sorted(list(set(t.get("symbol") for t in trades if t.get("symbol"))))

        realized_pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed_trades), 2)

        # Open positions are MARKED TO MARKET, not assumed flat.
        #
        # This previously summed `t.get("unrealized_pnl") or 0` over open trades — a field
        # PaperTradeLedgerEngine.open_trade() never writes. It was structurally always
        # zero, so an open position contributed exactly nothing to equity no matter how far
        # underwater it was. That is the don't-close-the-losers bias made automatic: close
        # the winners, hold the losers, and the summary reports rising equity, a 100% win
        # rate and no drawdown. The missing field looked like a real value of 0.
        unrealized_pnl, unvalued = self._mark_open_positions(open_trades)

        # If some open position cannot be priced, equity is UNKNOWN rather than "as if
        # flat". Reporting a number that silently omits unpriceable risk is the failure
        # this fix exists to remove, so the honest answer is None plus a reason.
        equity_complete = not unvalued
        latest_equity = (round(starting_equity + realized_pnl + unrealized_pnl, 2)
                         if equity_complete else None)
        highest_equity = max(starting_equity, latest_equity) if equity_complete else None
        total_return_pct = (round(((latest_equity - starting_equity) / starting_equity) * 100, 2)
                            if equity_complete else None)

        wins = [t for t in closed_trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in closed_trades if float(t.get("realized_pnl") or 0) < 0]

        # None, not 0, with no closed trades — a fresh ledger reported "0% win rate", which
        # reads as measured failure rather than no measurement. The denominator is closed
        # trades only, so a book that holds its losers open reports a win rate over its
        # winners alone: open_trade_count is the number to read alongside this.
        win_rate_pct = (round((len(wins) / len(closed_trades)) * 100, 2)
                        if closed_trades else None)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "starting_equity": starting_equity,
            "latest_equity": latest_equity,
            "highest_equity": highest_equity,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_return_pct": total_return_pct,
            # Equity is None when some open position could not be priced. Consumers must
            # check this rather than treating a missing mark as a flat position.
            "equity_complete": equity_complete,
            "unvalued_open_symbols": unvalued,
            # None, not 0, when there is no drawdown history: "no data" and "never drew
            # down" were previously the same output.
            "max_drawdown_pct": PaperDrawdownEngine().calculate().get("max_drawdown_pct"),
            "snapshot_count": 1,
            "paper_trade_count": len(trades),
            "open_trade_count": len(open_trades),
            "closed_trade_count": len(closed_trades),
            "symbols_traded": symbols,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": win_rate_pct,
            "status": "PERFORMANCE_SUMMARY_READY"
        }
