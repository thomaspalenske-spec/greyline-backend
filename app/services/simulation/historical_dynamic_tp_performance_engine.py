from datetime import datetime
from pathlib import Path

from app.services.simulation.historical_market_data_provider import HistoricalMarketDataProvider
from app.services.simulation.historical_opportunity_scoring_engine import HistoricalOpportunityScoringEngine


class HistoricalDynamicTPPerformanceEngine:
    """
    Simulator-only performance evaluator using GreyLine-style staged exits.

    Rule:
      Simulator adapts to GreyLine.
      Production/live GreyLine engines are not modified.

    Model:
      - Enter at signal close
      - TP1 sells 25%
      - TP2 sells 25%
      - TP3 sells 25%
      - TP4 is runner / final 25%
      - Stop exits remaining position
      - Time exit exits remaining position
    """

    def evaluate(
        self,
        start_date="1998-01-02",
        end_date="1999-12-31",
        hold_days=10,
        stop_loss_pct=-3.0,
        tp1_pct=3.0,
        tp2_pct=6.0,
        tp3_pct=9.0,
        runner_trail_pct=-4.0,
        max_trades_per_day=1,
    ):
        symbols = sorted(
            p.name.replace("_daily.csv", "")
            for p in Path("app/data/historical").glob("*_daily.csv")
        )

        provider = HistoricalMarketDataProvider()
        scorer = HistoricalOpportunityScoringEngine()

        dates = sorted(set(
            d
            for symbol in symbols
            for d in provider.available_dates(symbol, start_date, end_date)
        ))

        trades = []
        execute_seen = 0

        for d in dates:
            scored = scorer.score_universe_snapshot(symbols, d)
            executes = [
                o for o in scored.get("opportunities", [])
                if o.get("result") == "EXECUTE"
            ]

            executes = sorted(
                executes,
                key=lambda x: x.get("composite_score") or 0,
                reverse=True,
            )[:max_trades_per_day]

            for signal in executes:
                execute_seen += 1
                trade = self._evaluate_trade(
                    provider=provider,
                    signal=signal,
                    entry_date=d,
                    end_date=end_date,
                    hold_days=hold_days,
                    stop_loss_pct=stop_loss_pct,
                    tp1_pct=tp1_pct,
                    tp2_pct=tp2_pct,
                    tp3_pct=tp3_pct,
                    runner_trail_pct=runner_trail_pct,
                )
                if trade:
                    trades.append(trade)

        wins = [t for t in trades if t["return_pct"] > 0]
        losses = [t for t in trades if t["return_pct"] <= 0]

        gross_win = sum(t["return_pct"] for t in wins)
        gross_loss = abs(sum(t["return_pct"] for t in losses))

        tp1_count = len([t for t in trades if t["tp1_hit"]])
        tp2_count = len([t for t in trades if t["tp2_hit"]])
        tp3_count = len([t for t in trades if t["tp3_hit"]])
        runner_positive_count = len([t for t in trades if t["runner_return_pct"] > 0])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HistoricalDynamicTPPerformanceEngine",
            "start_date": start_date,
            "end_date": end_date,
            "symbols_scored": len(symbols),
            "trading_days": len(dates),
            "execute_signals_seen": execute_seen,
            "trade_count": len(trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round((len(wins) / len(trades)) * 100, 2) if trades else 0,
            "avg_win_pct": round(gross_win / len(wins), 2) if wins else 0,
            "avg_loss_pct": round(-(gross_loss / len(losses)), 2) if losses else 0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "total_return_pct_sum": round(sum(t["return_pct"] for t in trades), 2),
            "tp1_hit_rate_pct": round((tp1_count / len(trades)) * 100, 2) if trades else 0,
            "tp2_hit_rate_pct": round((tp2_count / len(trades)) * 100, 2) if trades else 0,
            "tp3_hit_rate_pct": round((tp3_count / len(trades)) * 100, 2) if trades else 0,
            "runner_positive_rate_pct": round((runner_positive_count / len(trades)) * 100, 2) if trades else 0,
            "hold_days": hold_days,
            "stop_loss_pct": stop_loss_pct,
            "tp1_pct": tp1_pct,
            "tp2_pct": tp2_pct,
            "tp3_pct": tp3_pct,
            "runner_trail_pct": runner_trail_pct,
            "max_trades_per_day": max_trades_per_day,
            "top_25_trades": sorted(trades, key=lambda x: x["return_pct"], reverse=True)[:25],
            "worst_25_trades": sorted(trades, key=lambda x: x["return_pct"])[:25],
            "status": "HISTORICAL_DYNAMIC_TP_PERFORMANCE_READY",
        }

    def _evaluate_trade(
        self,
        provider,
        signal,
        entry_date,
        end_date,
        hold_days,
        stop_loss_pct,
        tp1_pct,
        tp2_pct,
        tp3_pct,
        runner_trail_pct,
    ):
        symbol = signal.get("symbol")
        option_type = str(signal.get("option_type") or "").upper()
        direction = str(signal.get("directional_bias") or "").upper()

        dates = provider.available_dates(symbol, entry_date, end_date)
        if entry_date not in dates:
            return None

        entry_idx = dates.index(entry_date)
        forward_dates = dates[entry_idx + 1: entry_idx + 1 + hold_days]
        if not forward_dates:
            return None

        entry_md = provider.get_snapshot(symbol, entry_date)
        entry_price = entry_md.get("close")
        if not entry_price:
            return None

        remaining = 1.0
        realized_return = 0.0
        exits = []

        tp1_hit = False
        tp2_hit = False
        tp3_hit = False

        high_water_return = 0.0
        max_favorable_pct = 0.0
        max_adverse_pct = 0.0
        runner_return_pct = 0.0

        exit_reason = "TIME_EXIT"
        final_exit_date = forward_dates[-1]
        active_stop_pct = stop_loss_pct

        def ret_from_close(close):
            if direction == "BEARISH" or option_type == "PUT":
                return ((entry_price - close) / entry_price) * 100
            return ((close - entry_price) / entry_price) * 100

        for d in forward_dates:
            close = provider.get_snapshot(symbol, d).get("close")
            if not close:
                continue

            ret_pct = ret_from_close(close)
            high_water_return = max(high_water_return, ret_pct)
            max_favorable_pct = max(max_favorable_pct, ret_pct)
            max_adverse_pct = min(max_adverse_pct, ret_pct)

            if ret_pct <= active_stop_pct:
                if remaining > 0:
                    realized_return += remaining * ret_pct

                    if active_stop_pct >= tp2_pct:
                        stop_stage = "TP2_PROTECTIVE_STOP"
                    elif active_stop_pct >= 0:
                        stop_stage = "BREAKEVEN_STOP"
                    else:
                        stop_stage = "INITIAL_STOP"

                    exits.append({
                        "date": d,
                        "stage": stop_stage,
                        "weight": round(remaining, 2),
                        "return_pct": round(ret_pct, 2),
                        "active_stop_pct": round(active_stop_pct, 2),
                    })
                    runner_return_pct = ret_pct if remaining <= 0.25 else 0
                    remaining = 0

                exit_reason = stop_stage
                final_exit_date = d
                break

            if not tp1_hit and ret_pct >= tp1_pct and remaining >= 0.75:
                realized_return += 0.25 * ret_pct
                remaining -= 0.25
                tp1_hit = True
                active_stop_pct = max(active_stop_pct, 0.0)
                exits.append({
                    "date": d,
                    "stage": "TP1",
                    "weight": 0.25,
                    "return_pct": round(ret_pct, 2),
                    "new_stop_pct": round(active_stop_pct, 2),
                })

            if not tp2_hit and ret_pct >= tp2_pct and remaining >= 0.50:
                realized_return += 0.25 * ret_pct
                remaining -= 0.25
                tp2_hit = True
                active_stop_pct = max(active_stop_pct, tp1_pct)
                exits.append({
                    "date": d,
                    "stage": "TP2",
                    "weight": 0.25,
                    "return_pct": round(ret_pct, 2),
                    "new_stop_pct": round(active_stop_pct, 2),
                })

            if not tp3_hit and ret_pct >= tp3_pct and remaining >= 0.25:
                realized_return += 0.25 * ret_pct
                remaining -= 0.25
                tp3_hit = True
                active_stop_pct = max(active_stop_pct, tp2_pct)
                exits.append({
                    "date": d,
                    "stage": "TP3",
                    "weight": 0.25,
                    "return_pct": round(ret_pct, 2),
                    "new_stop_pct": round(active_stop_pct, 2),
                })

            if tp3_hit and remaining > 0:
                trail_stop = high_water_return + runner_trail_pct
                if ret_pct <= trail_stop:
                    realized_return += remaining * ret_pct
                    runner_return_pct = ret_pct
                    exits.append({"date": d, "stage": "RUNNER_TRAIL", "weight": round(remaining, 2), "return_pct": round(ret_pct, 2)})
                    remaining = 0
                    exit_reason = "RUNNER_TRAIL_EXIT"
                    final_exit_date = d
                    break

        if remaining > 0:
            final_close = provider.get_snapshot(symbol, final_exit_date).get("close")
            final_ret_pct = ret_from_close(final_close) if final_close else 0
            realized_return += remaining * final_ret_pct
            if remaining <= 0.25:
                runner_return_pct = final_ret_pct
            exits.append({"date": final_exit_date, "stage": "TIME_EXIT", "weight": round(remaining, 2), "return_pct": round(final_ret_pct, 2)})

        return {
            "symbol": symbol,
            "entry_date": entry_date,
            "exit_date": final_exit_date,
            "entry_price": entry_price,
            "return_pct": round(realized_return, 2),
            "winner": realized_return > 0,
            "exit_reason": exit_reason,
            "score": signal.get("composite_score"),
            "risk_state_score": signal.get("risk_state_score"),
            "regime_score": signal.get("regime_score"),
            "directional_bias": direction,
            "option_type": option_type,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "tp3_hit": tp3_hit,
            "runner_return_pct": round(runner_return_pct, 2),
            "max_favorable_pct": round(max_favorable_pct, 2),
            "max_adverse_pct": round(max_adverse_pct, 2),
            "exits": exits,
        }
