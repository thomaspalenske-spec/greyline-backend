from datetime import datetime
from app.services.research.historical_trade_warehouse_engine import HistoricalTradeWarehouseEngine
from pathlib import Path
import csv

from app.services.simulation.historical_dynamic_tp_performance_engine import HistoricalDynamicTPPerformanceEngine


class HistoricalAccountSimulationEngine:
    """
    Account-level historical simulator.

    Uses simulator-side GreyLine emulation results and converts percent returns
    into realized account P&L with position sizing.

    Safety:
      Historical simulation only.
      Does not affect live/paper ledgers.
      Does not place orders.
    """

    def run(
        self,
        start_date="1998-01-01",
        end_date=None,
        starting_balance=10000.0,
        max_position_pct=0.10,
        max_trades_per_day=1,
        hold_days=10,
        stop_loss_pct=-3.0,
        tp1_pct=3.0,
        tp2_pct=6.0,
        tp3_pct=9.0,
        runner_trail_pct=-4.0,
    ):
        if end_date is None:
            end_date = self._latest_historical_date()

        perf = HistoricalDynamicTPPerformanceEngine().evaluate(
            start_date=start_date,
            end_date=end_date,
            hold_days=hold_days,
            stop_loss_pct=stop_loss_pct,
            tp1_pct=tp1_pct,
            tp2_pct=tp2_pct,
            tp3_pct=tp3_pct,
            runner_trail_pct=runner_trail_pct,
            max_trades_per_day=max_trades_per_day,
        )

        balance = float(starting_balance)
        equity_curve = []
        realized_trades = []

        for i, trade in enumerate(perf.get("trades") or [], start=1):
            entry_balance = balance
            position_size = round(entry_balance * float(max_position_pct), 2)
            ret_pct = float(trade.get("return_pct") or 0)
            realized_pnl = round(position_size * (ret_pct / 100.0), 2)
            balance = round(balance + realized_pnl, 2)

            row = {
                "trade_number": i,
                "symbol": trade.get("symbol"),
                "entry_date": trade.get("entry_date"),
                "exit_date": trade.get("exit_date"),
                "exit_policy": trade.get("exit_policy"),
                "exit_reason": trade.get("exit_reason"),
                "score": trade.get("score"),
                "return_pct": ret_pct,
                "entry_balance": round(entry_balance, 2),
                "position_size": position_size,
                "realized_pnl": realized_pnl,
                "ending_balance": balance,
                "winner": realized_pnl > 0,
            }

            realized_trades.append(row)
            equity_curve.append({
                "trade_number": i,
                "date": trade.get("exit_date"),
                "balance": balance,
            })

        wins = [t for t in realized_trades if t["winner"]]
        losses = [t for t in realized_trades if not t["winner"]]

        gross_profit = round(sum(t["realized_pnl"] for t in wins), 2)
        gross_loss = round(sum(t["realized_pnl"] for t in losses), 2)
        net_profit = round(balance - float(starting_balance), 2)

        avg_win = round(gross_profit / len(wins), 2) if wins else 0
        avg_loss = round(gross_loss / len(losses), 2) if losses else 0

        peak = float(starting_balance)
        max_drawdown_pct = 0.0
        for point in equity_curve:
            bal = float(point.get("balance") or 0)
            if bal > peak:
                peak = bal
            if peak > 0:
                dd = ((bal - peak) / peak) * 100.0
                if dd < max_drawdown_pct:
                    max_drawdown_pct = dd
        max_drawdown_pct = round(max_drawdown_pct, 2)

        HistoricalTradeWarehouseEngine().save(
            simulation_name="account_simulation",
            trades=realized_trades,
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HistoricalAccountSimulationEngine",
            "simulation_mode": "ACCOUNT_LEVEL_REALIZED_PNL",
            "start_date": start_date,
            "end_date": end_date,
            "starting_balance": round(float(starting_balance), 2),
            "ending_balance": balance,
            "net_profit": net_profit,
            "total_return_pct": round((net_profit / float(starting_balance)) * 100.0, 2) if starting_balance else 0,
            "trade_count": len(realized_trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round((len(wins) / len(realized_trades)) * 100.0, 2) if realized_trades else 0,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": round(gross_profit / abs(gross_loss), 2) if gross_loss else None,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown_pct": max_drawdown_pct,
            "max_position_pct": max_position_pct,
            "max_trades_per_day": max_trades_per_day,
            "source_performance": {
                "trade_count": perf.get("trade_count"),
                "win_rate_pct": perf.get("win_rate_pct"),
                "avg_win_pct": perf.get("avg_win_pct"),
                "avg_loss_pct": perf.get("avg_loss_pct"),
                "profit_factor": perf.get("profit_factor"),
                "total_return_pct_sum": perf.get("total_return_pct_sum"),
                "status": perf.get("status"),
            },
            "top_10_realized_trades": sorted(realized_trades, key=lambda x: x["realized_pnl"], reverse=True)[:10],
            "worst_10_realized_trades": sorted(realized_trades, key=lambda x: x["realized_pnl"])[:10],
            "equity_curve_tail": equity_curve[-20:],
            "realized_trades": realized_trades,
            "future_visible": False,
            "live_execution_enabled": False,
            "status": "HISTORICAL_ACCOUNT_SIMULATION_READY",
        }

    def _latest_historical_date(self):
        dates = []
        for path in Path("app/data/historical").glob("*_daily.csv"):
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                dates.append(rows[-1]["date"])
        return max(dates) if dates else datetime.utcnow().date().isoformat()
