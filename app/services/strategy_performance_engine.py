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
            return [], 0.0, []
        try:
            series, _asof, _src = MomentumReversalStrategyEngine().universe()
            last = {s: c[-1] for s, c in series.items() if c}
        except Exception:
            last = {}

        cost_bps = MomentumReversalStrategyEngine.COST_BPS_ROUND_TRIP
        rows, total = [], 0.0
        unpriced = []
        for t in open_trades:
            entry = float(t.get("entry_price") or 0)
            qty = float(t.get("quantity") or 0)
            # An unavailable price is NOT "unchanged". This defaulted to the entry price
            # via two silent paths — the bare except above setting last={}, and
            # .get(sym, entry) or entry — so gross evaluated to exactly 0 and an open
            # position contributed only -cost. Holding a loser looked free, and since
            # universe() calls a live feed, an outage or an off-hours run marked the ENTIRE
            # open book flat. The same defect was confirmed in
            # paper_performance_summary_engine: unknown must be reported, not assumed.
            quoted = last.get(t.get("symbol"))
            priced = isinstance(quoted, (int, float)) and quoted > 0
            if not priced:
                unpriced.append(t.get("symbol"))
                rows.append({"symbol": t.get("symbol"), "side": t.get("side"),
                             "entry_price": entry, "current_price": None,
                             "pnl": None, "priced": False})
                continue
            cur = float(quoted)
            direction = -1 if str(t.get("side") or "").upper() in ("SELL", "SELL_SHORT", "SHORT") else 1
            gross = (cur - entry) * qty * direction
            # Net of the round trip it takes to be in and out of this position — i.e.
            # what you'd actually keep if you closed it now.
            cost = abs(entry * qty) * (cost_bps / 10000.0)
            pnl = gross - cost
            total += pnl
            rows.append({"symbol": t.get("symbol"), "side": t.get("side"),
                         "entry_price": entry, "current_price": round(cur, 2),
                         "unrealized_pnl_gross": round(gross, 2),
                         "transaction_cost": round(cost, 2),
                         "unrealized_pnl": round(pnl, 2), "priced": True})
        return rows, total, unpriced

    def evaluate(self):
        trades = [t for t in PaperTradeLedgerEngine()._read_all()
                  if t.get("trade_intent") == self.TRADE_INTENT]
        closed = sorted([t for t in trades if t.get("status") == "CLOSED"], key=self._closed_at)
        open_trades = [t for t in trades if t.get("status") == "OPEN"]

        # Net of transaction cost. The ledger's realized_pnl is the raw price move — a
        # frictionless number. Judging the edge on that would be fantasy: the backtest's
        # out-of-sample Sharpe fell 0.42 -> 0.08 once 10bps of round-trip cost was charged.
        # Cost is derived from entry notional (not stamped on the trade), so this applies
        # retroactively to fills already recorded.
        cost_bps = MomentumReversalStrategyEngine.COST_BPS_ROUND_TRIP

        def _cost(t):
            notional = abs(float(t.get("entry_price") or 0) * float(t.get("quantity") or 0))
            return notional * (cost_bps / 10000.0)

        gross_pnls = [float(t.get("realized_pnl") or 0) for t in closed]
        costs = [_cost(t) for t in closed]
        pnls = [g - c for g, c in zip(gross_pnls, costs)]     # net — everything below uses this
        n = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        realized_gross = round(sum(gross_pnls), 2)
        total_costs = round(sum(costs), 2)
        realized = round(sum(pnls), 2)

        # Equity curve over closed trades (cumulative NET realized).
        curve, cum = [], 0.0
        for t, p in zip(closed, pnls):
            cum += p
            curve.append({"at": self._closed_at(t)[:19], "symbol": t.get("symbol"),
                          "pnl": round(p, 2), "cumulative": round(cum, 2)})

        expectancy = round(sum(pnls) / n, 2) if n else 0.0

        # Independence. t = mean / (sd / sqrt(n)) assumes n INDEPENDENT trades, but
        # record_paper_trades() opens top_n positions in a SINGLE call, all selected from
        # one market snapshot on one day, and there is no duplicate-open guard so repeated
        # cycles re-open the same names. Those P&Ls are dominated by one shared market move.
        # Dividing by sqrt(row count) inflated t by roughly the square root of the
        # correlation multiple — and t > 2 is exactly what prints POSITIVE_EDGE_EMERGING.
        # A distinct symbol-day is the honest unit, matching fixed_horizon_grader_engine.
        effective_n = len({(t.get("symbol"), self._closed_at(t)[:10]) for t in closed})

        t_stat = None
        if n >= 2 and effective_n >= 2:
            mean = sum(pnls) / n
            var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
            sd = math.sqrt(var)
            t_stat = round(mean / (sd / math.sqrt(effective_n)), 2) if sd > 0 else None

        open_rows, unrealized, unpriced_open = self._mark_open(open_trades)
        total = round(realized + unrealized, 2)

        # The guard applies to the EFFECTIVE count. Thirty trades opened on three days is
        # three observations, and clearing the threshold on row count is how a handful of
        # correlated bets earns a verdict.
        under_min = effective_n < self.MIN_TRADES_FOR_SIGNAL
        if under_min:
            verdict = "INSUFFICIENT_SAMPLE"
            headline = (f"{n} closed trade(s) across {effective_n} independent symbol-day(s)"
                        f" — far too few to judge. Need ~{self.MIN_TRADES_FOR_SIGNAL}+"
                        " independent observations before the P&L means anything.")
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
            # Headline metrics are SUPPRESSED below the same minimum that gates the
            # verdict. They were computed unconditionally, so a payload could carry
            # win_rate_pct 100.0 and profit_factor 4.2 next to verdict INSUFFICIENT_SAMPLE,
            # and any consumer reading the metrics rather than the verdict string saw a
            # spectacular edge on n=1. Identical bypass to the one fixed in
            # fixed_horizon_grader_engine.
            "win_rate_pct": (round(100 * len(wins) / n, 1) if n and not under_min else None),
            "effective_n_symbol_days": effective_n,
            "suppressed_below_min_sample": under_min,
            "unpriced_open_symbols": unpriced_open,
            "cost_bps_round_trip": cost_bps,
            "realized_pnl_gross": realized_gross,
            "transaction_costs": total_costs,
            "realized_pnl": realized,
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": total,
            "return_pct_on_capital": (round(100 * total / self.capital_base, 2)
                                      if self.capital_base and not under_min else None),
            "expectancy_per_trade": (expectancy if not under_min else None),
            "expectancy_t_stat": t_stat,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": (round(sum(wins) / abs(sum(losses)), 2)
                              if losses and sum(losses) != 0 and not under_min else None),
            "capital_base": self.capital_base,
            "open_positions": open_rows,
            "equity_curve": curve,
            "note": (f"All P&L is NET of {cost_bps}bps round-trip cost — the verdict is judged "
                     f"on what you'd actually keep, not a frictionless fill. A t-stat beyond "
                     f"+/-2 is the bar for a real edge, and only once the sample is large "
                     f"enough to trust."),
            "status": "STRATEGY_PERFORMANCE_READY",
        }
