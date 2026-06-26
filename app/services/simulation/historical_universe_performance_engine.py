from datetime import datetime
from pathlib import Path
import json

from app.services.simulation.historical_market_data_provider import HistoricalMarketDataProvider
from app.services.simulation.historical_opportunity_scoring_engine import HistoricalOpportunityScoringEngine


class HistoricalUniversePerformanceEngine:
    """
    Simulator-only universe performance evaluator.

    Rule:
      Simulator adapts to GreyLine.
      Production/live GreyLine engines are not modified.

    Evaluates historical EXECUTE signals using forward OHLCV data only after
    the signal date. Entry is current close. Exit is stop, take-profit, or time.
    """

    def evaluate(
        self,
        start_date="1998-01-02",
        end_date="2026-06-25",
        hold_days=3,
        stop_loss_pct=-3.0,
        take_profit_pct=6.0,
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
                    take_profit_pct=take_profit_pct,
                )
                if trade:
                    trades.append(trade)

        wins = [t for t in trades if t["return_pct"] > 0]
        losses = [t for t in trades if t["return_pct"] <= 0]

        gross_win = sum(t["return_pct"] for t in wins)
        gross_loss = abs(sum(t["return_pct"] for t in losses))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HistoricalUniversePerformanceEngine",
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
            "hold_days": hold_days,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "max_trades_per_day": max_trades_per_day,
            "top_25_trades": sorted(trades, key=lambda x: x["return_pct"], reverse=True)[:25],
            "worst_25_trades": sorted(trades, key=lambda x: x["return_pct"])[:25],
            "status": "HISTORICAL_UNIVERSE_PERFORMANCE_READY",
        }

    def _evaluate_trade(
        self,
        provider,
        signal,
        entry_date,
        end_date,
        hold_days,
        stop_loss_pct,
        take_profit_pct,
    ):
        symbol = signal.get("symbol")
        option_type = str(signal.get("option_type") or "").upper()
        direction = str(signal.get("directional_bias") or "").upper()

        dates = provider.available_dates(symbol, entry_date, end_date)
        if entry_date not in dates:
            return None

        entry_idx = dates.index(entry_date)
        entry_md = provider.get_snapshot(symbol, entry_date)
        entry_price = entry_md.get("close")

        if not entry_price:
            return None

        exit_reason = "TIME_EXIT"
        exit_date = None
        exit_price = None
        max_favorable_pct = 0
        max_adverse_pct = 0

        forward_dates = dates[entry_idx + 1: entry_idx + 1 + hold_days]
        if not forward_dates:
            return None

        for d in forward_dates:
            md = provider.get_snapshot(symbol, d)
            close = md.get("close")
            if not close:
                continue

            if direction == "BEARISH" or option_type == "PUT":
                ret_pct = ((entry_price - close) / entry_price) * 100
            else:
                ret_pct = ((close - entry_price) / entry_price) * 100

            max_favorable_pct = max(max_favorable_pct, ret_pct)
            max_adverse_pct = min(max_adverse_pct, ret_pct)

            if ret_pct <= stop_loss_pct:
                exit_reason = "STOP_LOSS"
                exit_date = d
                exit_price = close
                break

            if ret_pct >= take_profit_pct:
                exit_reason = "TAKE_PROFIT"
                exit_date = d
                exit_price = close
                break

        if exit_price is None:
            exit_date = forward_dates[-1]
            exit_price = provider.get_snapshot(symbol, exit_date).get("close")

        if not exit_price:
            return None

        if direction == "BEARISH" or option_type == "PUT":
            return_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            return_pct = ((exit_price - entry_price) / entry_price) * 100

        return {
            "symbol": symbol,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": round(return_pct, 2),
            "winner": return_pct > 0,
            "exit_reason": exit_reason,
            "score": signal.get("composite_score"),
            "risk_state_score": signal.get("risk_state_score"),
            "regime_score": signal.get("regime_score"),
            "directional_bias": direction,
            "option_type": option_type,
            "max_favorable_pct": round(max_favorable_pct, 2),
            "max_adverse_pct": round(max_adverse_pct, 2),
        }
