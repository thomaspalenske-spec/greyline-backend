from datetime import datetime


class SimulationPerformanceEngine:
    """
    First performance simulator.

    It takes replay steps + signal events and simulates simple long/short outcomes
    using no future data at signal time. Forward prices are only inspected after entry.
    """

    def evaluate(self, replay_steps, signal_events, hold_days=3, stop_loss_pct=-3.0, take_profit_pct=6.0):
        replay_steps = replay_steps or []
        signal_events = signal_events or []

        trades = []

        for i, signal in enumerate(signal_events):
            if not signal or not signal.get("candidate_available"):
                continue

            score = float(signal.get("score") or signal.get("composite_score") or signal.get("adjusted_score") or 0)
            liquidity = float(signal.get("liquidity_score") or 0)

            if score < 85 or liquidity < 70:
                continue

            entry_step = replay_steps[i] if i < len(replay_steps) else None
            entry_md = (entry_step or {}).get("market_data") or {}
            entry_price = entry_md.get("close")

            if not entry_price:
                continue

            direction = str(signal.get("directional_bias") or "").upper()
            option_type = str(signal.get("option_type") or "").upper()

            exit_index = min(i + hold_days, len(replay_steps) - 1)
            forward_window = replay_steps[i + 1: exit_index + 1]

            if not forward_window:
                continue

            exit_reason = "TIME_EXIT"
            exit_price = None
            max_favorable_pct = 0
            max_adverse_pct = 0

            for step in forward_window:
                md = step.get("market_data") or {}
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
                    exit_price = close
                    break

                if ret_pct >= take_profit_pct:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = close
                    break

            if exit_price is None:
                last_md = (forward_window[-1] or {}).get("market_data") or {}
                exit_price = last_md.get("close")

            if not exit_price:
                continue

            if direction == "BEARISH" or option_type == "PUT":
                return_pct = round(((entry_price - exit_price) / entry_price) * 100, 2)
            else:
                return_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)

            trades.append({
                "entry_timestamp": entry_step.get("timestamp"),
                "exit_timestamp": replay_steps[exit_index].get("timestamp") if exit_index < len(replay_steps) else None,
                "symbol": signal.get("symbol"),
                "option_type": option_type,
                "directional_bias": direction,
                "score": score,
                "liquidity_score": liquidity,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": return_pct,
                "winner": return_pct > 0,
                "exit_reason": exit_reason,
                "hold_days": hold_days,
                "max_favorable_pct": round(max_favorable_pct, 2),
                "max_adverse_pct": round(max_adverse_pct, 2),
            })

        wins = [t for t in trades if t["winner"]]
        losses = [t for t in trades if not t["winner"]]

        avg_win = round(sum(t["return_pct"] for t in wins) / len(wins), 2) if wins else 0
        avg_loss = round(sum(t["return_pct"] for t in losses) / len(losses), 2) if losses else 0
        total_return = round(sum(t["return_pct"] for t in trades), 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "SimulationPerformanceEngine",
            "trade_count": len(trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round((len(wins) / len(trades)) * 100, 2) if trades else 0,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "total_return_pct": total_return,
            "trades": trades,
            "status": "SIMULATION_PERFORMANCE_READY",
        }
