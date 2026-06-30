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
        max_account_drawdown_pct=-25.0,
        recovery_resume_drawdown_pct=-18.0,
        recovery_position_pct=0.03,
        min_cash_balance_pct=0.25,
        halt_on_drawdown=True,
        universe_mode="ALL_TRADED_EQUITIES",
        include_equities=True,
        include_calls=True,
        include_puts=True,
        aperture=1.0,
        walk_forward=True,
        no_lookahead=True,
        as_of_timeline_only=True,
    ):
        if end_date is None:
            end_date = self._latest_historical_date()

        lookahead_enforced = (
            walk_forward is True
            and no_lookahead is True
            and as_of_timeline_only is True
        )

        if not lookahead_enforced:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "engine": "HistoricalAccountSimulationEngine",
                "status": "SIMULATION_REJECTED_LOOKAHEAD_DISCIPLINE_NOT_ENFORCED",
                "future_visible": True,
                "live_execution_enabled": False,
            }

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
            universe_mode=universe_mode,
            include_equities=include_equities,
            include_calls=include_calls,
            include_puts=include_puts,
            aperture=aperture,
            walk_forward=walk_forward,
            no_lookahead=no_lookahead,
            as_of_timeline_only=as_of_timeline_only,
        )

        balance = float(starting_balance)
        equity_curve = []
        realized_trades = []

        peak_balance = balance
        halted = False
        recovery_mode = False
        halt_reason = None
        skipped_trades = 0
        resumed_trades = 0
        recovery_trades = 0

        for i, trade in enumerate(perf.get("trades") or [], start=1):
            if balance > peak_balance:
                peak_balance = balance

            current_drawdown_pct = ((balance - peak_balance) / peak_balance) * 100.0 if peak_balance else 0

            if halt_on_drawdown and current_drawdown_pct <= max_account_drawdown_pct:
                halted = True
                recovery_mode = True
                halt_reason = "MAX_ACCOUNT_DRAWDOWN_RECOVERY_MODE"

            if recovery_mode and current_drawdown_pct >= recovery_resume_drawdown_pct:
                recovery_mode = False
                resumed_trades += 1

            if balance <= float(starting_balance) * float(min_cash_balance_pct):
                halted = True
                halt_reason = "MIN_CASH_BALANCE_HALT"
                skipped_trades += 1
                continue

            entry_balance = balance
            if current_drawdown_pct <= -22.0:
                skipped_trades += 1
                continue
            elif current_drawdown_pct <= -18.0:
                active_position_pct = 0.005
                recovery_mode = True
            elif current_drawdown_pct <= -18.0:
                active_position_pct = 0.02
                recovery_mode = True
            elif current_drawdown_pct <= -10.0:
                active_position_pct = 0.05
                recovery_mode = True
            else:
                active_position_pct = max_position_pct

            if recovery_mode:
                recovery_trades += 1
            position_size = round(entry_balance * float(active_position_pct), 2)
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
                "recovery_mode": recovery_mode,
                "active_position_pct": active_position_pct,
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
            "simulation_mode": "ACCOUNT_LEVEL_REALIZED_PNL_FULL_APERTURE_WALK_FORWARD",
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
            "portfolio_governor": {
                "enabled": True,
                "halted": halted,
                "halt_reason": halt_reason,
                "max_account_drawdown_pct": max_account_drawdown_pct,
                "min_cash_balance_pct": min_cash_balance_pct,
                "recovery_resume_drawdown_pct": recovery_resume_drawdown_pct,
                "recovery_position_pct": recovery_position_pct,
                "tiered_drawdown_sizing": {
                    "normal": max_position_pct,
                    "drawdown_10_pct": 0.05,
                    "drawdown_18_pct": 0.02,
                    "drawdown_22_pct": 0.005,
                    "drawdown_25_pct": "SKIP_TRADE"
                },
                "recovery_mode": recovery_mode,
                "skipped_trades": skipped_trades,
                "resumed_trades": resumed_trades,
                "recovery_trades": recovery_trades,
            },
            "max_trades_per_day": max_trades_per_day,
            "universe_mode": universe_mode,
            "include_equities": include_equities,
            "include_calls": include_calls,
            "include_puts": include_puts,
            "aperture": aperture,
            "walk_forward": walk_forward,
            "no_lookahead": no_lookahead,
            "as_of_timeline_only": as_of_timeline_only,
            "lookahead_enforced": lookahead_enforced,
            "source_performance": {
                "trade_count": perf.get("trade_count"),
                "win_rate_pct": perf.get("win_rate_pct"),
                "avg_win_pct": perf.get("avg_win_pct"),
                "avg_loss_pct": perf.get("avg_loss_pct"),
                "profit_factor": perf.get("profit_factor"),
                "total_return_pct_sum": perf.get("total_return_pct_sum"),
                "status": perf.get("status"),
                "universe_mode": perf.get("universe_mode"),
                "symbols_scored": perf.get("symbols_scored"),
                "trading_days": perf.get("trading_days"),
                "execute_signals_seen": perf.get("execute_signals_seen"),
                "lookahead_enforced": perf.get("lookahead_enforced"),
                "future_visible": perf.get("future_visible"),
                "aperture_limit_note": perf.get("aperture_limit_note"),
            },
            "top_10_realized_trades": sorted(realized_trades, key=lambda x: x["realized_pnl"], reverse=True)[:10],
            "worst_10_realized_trades": sorted(realized_trades, key=lambda x: x["realized_pnl"])[:10],
            "equity_curve_tail": equity_curve[-20:],
            "realized_trades": realized_trades,
            "future_visible": False,
            "timeline_awareness": "AS_OF_EACH_SIMULATED_DATE_ONLY",
            "aperture_note": "Account engine accepts full-aperture intent. Source performance engine still determines actual historical universe coverage.",
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
