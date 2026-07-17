import math
from datetime import datetime

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine


class StrategyPerformanceEngine:
    """
    The verdict instrument: does the rebuilt strategy actually make money forward?

    Derived entirely from the trade ledger, so it is reconstructible at any time and
    never depends on a state file that could drift. Realized P&L comes from closed
    MOMENTUM_REVERSAL trades; unrealized marks the open book to the latest close.

    Deliberately refuses to imply significance from a small sample. A ~51-53% edge needs
    hundreds of trades to separate from chance — the whole failure mode of this project
    has been concluding from n=1. Below MIN_TRADES_FOR_SIGNAL the verdict is
    INSUFFICIENT_SAMPLE no matter how good or bad the P&L looks, and the expectancy
    t-stat is reported so "is this distinguishable from zero" is answerable rather than
    eyeballed.
    """

    TRADE_INTENT = "MOMENTUM_REVERSAL"
    MIN_TRADES_FOR_SIGNAL = 30

    def __init__(self, capital_base=None):
        self.capital_base = float(capital_base) if capital_base else MomentumReversalStrategyEngine.CAPITAL_BASE

    @staticmethod
    def _closed_at(trade):
        return str(trade.get("exit_timestamp") or trade.get("closed_timestamp") or "")

    def _mark_open(self, open_trades):
        """Mark open positions to the latest close. Returns (rows, total_unrealized)."""
        if not open_trades:
            return [], 0.0
        try:
            series, _asof, _src = MomentumReversalStrategyEngine().universe()
            last = {s: c[-1] for s, c in series.items() if c}
        except Exception:
            last = {}

        rows, total = [], 0.0
        for t in open_trades:
            entry = float(t.get("entry_price") or 0)
            qty = float(t.get("quantity") or 0)
            cur = float(last.get(t.get("symbol"), entry) or entry)
            direction = -1 if str(t.get("side") or "").upper() in ("SELL", "SELL_SHORT", "SHORT") else 1
            pnl = (cur - entry) * qty * direction
            total += pnl
            rows.append({"symbol": t.get("symbol"), "side": t.get("side"),
                         "entry_price": entry, "current_price": round(cur, 2),
                         "unrealized_pnl": round(pnl, 2)})
        return rows, total

    def evaluate(self):
        trades = [t for t in PaperTradeLedgerEngine()._read_all()
                  if t.get("trade_intent") == self.TRADE_INTENT]
        closed = sorted([t for t in trades if t.get("status") == "CLOSED"], key=self._closed_at)
        open_trades = [t for t in trades if t.get("status") == "OPEN"]

        pnls = [float(t.get("realized_pnl") or 0) for t in closed]
        n = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        realized = round(sum(pnls), 2)

        # Equity curve over closed trades (cumulative realized).
        curve, cum = [], 0.0
        for t, p in zip(closed, pnls):
            cum += p
            curve.append({"at": self._closed_at(t)[:19], "symbol": t.get("symbol"),
                          "pnl": round(p, 2), "cumulative": round(cum, 2)})

        expectancy = round(sum(pnls) / n, 2) if n else 0.0
        # Is expectancy distinguishable from zero? t = mean / (sd / sqrt(n)).
        t_stat = None
        if n >= 2:
            mean = sum(pnls) / n
            var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
            sd = math.sqrt(var)
            t_stat = round(mean / (sd / math.sqrt(n)), 2) if sd > 0 else None

        open_rows, unrealized = self._mark_open(open_trades)
        total = round(realized + unrealized, 2)

        if n < self.MIN_TRADES_FOR_SIGNAL:
            verdict = "INSUFFICIENT_SAMPLE"
            headline = (f"{n} closed trade(s) — far too few to judge. Need ~"
                        f"{self.MIN_TRADES_FOR_SIGNAL}+ before the P&L means anything.")
        elif t_stat is not None and t_stat > 2:
            verdict = "POSITIVE_EDGE_EMERGING"
            headline = f"Expectancy ${expectancy}/trade over {n} trades is significantly > 0 (t={t_stat})."
        elif t_stat is not None and t_stat < -2:
            verdict = "NEGATIVE_EDGE_EMERGING"
            headline = f"Expectancy ${expectancy}/trade over {n} trades is significantly < 0 (t={t_stat})."
        else:
            verdict = "NO_DETECTABLE_EDGE"
            headline = f"Expectancy ${expectancy}/trade over {n} trades is not distinguishable from zero."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "StrategyPerformanceEngine",
            "strategy": self.TRADE_INTENT,
            "verdict": verdict,
            "headline": headline,
            "closed_trades": n,
            "min_trades_for_signal": self.MIN_TRADES_FOR_SIGNAL,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / n, 1) if n else None,
            "realized_pnl": realized,
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": total,
            "return_pct_on_capital": round(100 * total / self.capital_base, 2) if self.capital_base else None,
            "expectancy_per_trade": expectancy,
            "expectancy_t_stat": t_stat,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": (round(sum(wins) / abs(sum(losses)), 2)
                              if losses and sum(losses) != 0 else None),
            "capital_base": self.capital_base,
            "open_positions": open_rows,
            "equity_curve": curve,
            "note": ("Realized is from closed trades; unrealized marks the open book to the "
                     "latest close. A t-stat beyond +/-2 is the bar for a real edge — and "
                     "only once the sample is large enough to trust."),
            "status": "STRATEGY_PERFORMANCE_READY",
        }
