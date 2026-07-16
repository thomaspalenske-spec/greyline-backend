import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.persistence.json_store import atomic_write_text
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.dynamic_exit_policy_engine import DynamicExitPolicyEngine
from app.services.market_hours_engine import MarketHoursEngine


class PaperPositionManagerEngine:

    def __init__(self):
        self.ledger_file = Path("app/data/paper_trading/paper_trade_ledger.jsonl")

    def _parse_trade_time(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    def manage_open_positions(self):
        ledger = PaperTradeLedgerEngine().history()
        trades = ledger.get("trades", [])

        if not trades:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "positions_checked": 0,
                "positions_closed": 0,
                "status": "PAPER_POSITION_MANAGER_NO_TRADES",
            }

        updated = []
        closed = []
        stale_blocked = []
        market_hours = MarketHoursEngine().status()
        market_open = bool(market_hours.get('is_regular_session'))

        for trade in trades:
            if trade.get("status") != "OPEN":
                updated.append(trade)
                continue

            # Momentum-reversal positions are owned by MomentumReversalRebalanceEngine,
            # which exits on a fixed ~5-day schedule. This manager's take-profit/stop-loss
            # doctrine is a different, conflicting exit rule — left unguarded it closed the
            # strategy's positions out from under it (e.g. the MSTR short). Leave them be.
            if trade.get("trade_intent") == "MOMENTUM_REVERSAL":
                updated.append(trade)
                continue

            symbol = trade.get("symbol")
            entry_price = float(trade.get("entry_price") or 0)
            quantity = float(trade.get("quantity") or 0)

            quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
            quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
            quote_row = quotes[0] if quotes else {}

            try:
                current_price = float(quote_row.get("Last") or 0)
            except Exception:
                current_price = 0.0

            trade_time_raw = quote_row.get("TradeTime")
            trade_time = self._parse_trade_time(trade_time_raw)
            now = datetime.now(timezone.utc)
            quote_age_seconds = None if trade_time is None else round((now - trade_time).total_seconds(), 2)

            market_flags = quote_row.get("MarketFlags") or {}
            is_delayed = bool(market_flags.get("IsDelayed"))

            if entry_price <= 0 or current_price <= 0:
                trade["manager_status"] = "PRICE_UNAVAILABLE"
                trade["last_manager_block_reason"] = "PRICE_UNAVAILABLE"
                trade["last_manager_checked_at"] = datetime.utcnow().isoformat()
                updated.append(trade)
                continue

            if market_open and (is_delayed or quote_age_seconds is None or quote_age_seconds > 900):
                trade["manager_status"] = "STALE_QUOTE_BLOCKED"
                trade["last_manager_block_reason"] = "FRESH_NON_DELAYED_QUOTE_REQUIRED"
                trade["last_quote_trade_time"] = trade_time_raw
                trade["last_quote_age_seconds"] = quote_age_seconds
                trade["last_quote_is_delayed"] = is_delayed
                trade["last_manager_checked_at"] = datetime.utcnow().isoformat()
                stale_blocked.append({
                    "symbol": symbol,
                    "trade_time": trade_time_raw,
                    "quote_age_seconds": quote_age_seconds,
                    "is_delayed": is_delayed,
                })
                updated.append(trade)
                continue

            # Direction-aware P&L. This was long-only math: for a SHORT it inverted the
            # sign, so a winning short (price falling) read as a loss and tripped the
            # stop-loss on a profitable trade — which is exactly what closed the MSTR
            # short at a reported -$34.45 when it was really a +$34.45 gain.
            direction = -1 if str(trade.get("side") or "").upper() in ("SELL", "SELL_SHORT", "SHORT") else 1
            pnl = (current_price - entry_price) * quantity * direction
            pnl_pct = ((current_price / entry_price) - 1) * 100 * direction

            if not market_open:
                trade["current_price"] = current_price
                trade["unrealized_pnl"] = round(pnl, 2)
                trade["unrealized_pnl_pct"] = round(pnl_pct, 2)
                trade["position_action"] = "HOLD"
                trade["position_health"] = "MARKET_CLOSED"
                trade["manager_status"] = "MARKET_CLOSED_LAST_QUOTE_MARK"
                trade["market_state"] = market_hours.get("state")
                trade["last_quote_trade_time"] = trade_time_raw
                trade["last_quote_age_seconds"] = quote_age_seconds
                trade["last_quote_is_delayed"] = is_delayed
                trade["last_manager_checked_at"] = datetime.utcnow().isoformat()
                updated.append(trade)
                continue

            exit_policy = DynamicExitPolicyEngine().build_policy(
                symbol,
                composite_score=trade.get("composite_score")
            )
            take_profit_pct = exit_policy.get("take_profit_pct", 10)
            stop_loss_pct = exit_policy.get("stop_loss_pct", -5)
            should_close = pnl_pct >= take_profit_pct or pnl_pct <= stop_loss_pct

            trade["current_price"] = current_price
            trade["unrealized_pnl"] = round(pnl, 2)
            trade["unrealized_pnl_pct"] = round(pnl_pct, 2)
            trade["exit_policy"] = exit_policy.get("exit_policy")
            trade["volatility_score"] = exit_policy.get("volatility_score")
            trade["volatility_state"] = exit_policy.get("volatility_state")
            trade["volatility_band"] = exit_policy.get("volatility_band")
            trade["reward_multiple"] = exit_policy.get("reward_multiple")
            trade["take_profit_pct"] = take_profit_pct
            trade["stop_loss_pct"] = stop_loss_pct
            trade["distance_to_target_pct"] = round(take_profit_pct - pnl_pct, 2)
            trade["distance_to_stop_pct"] = round(pnl_pct - stop_loss_pct, 2)
            trade["position_action"] = "EXIT" if should_close else "HOLD"
            trade["position_health"] = "AT_RISK" if pnl_pct <= -3 else "HEALTHY"
            trade["manager_status"] = "MANAGED_WITH_FRESH_QUOTE"
            trade["last_quote_trade_time"] = trade_time_raw
            trade["last_quote_age_seconds"] = quote_age_seconds
            trade["last_quote_is_delayed"] = is_delayed
            trade["last_managed_at"] = datetime.utcnow().isoformat()

            if should_close:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = round(pnl, 2)
                trade["realized_pnl_pct"] = round(pnl_pct, 2)
                trade["exit_reason"] = "TAKE_PROFIT" if pnl_pct >= take_profit_pct else "STOP_LOSS"
                closed.append(trade)

            updated.append(trade)

        # Atomic + durable (also creates parent dir): a crash mid-write can never
        # truncate the ledger, and the write no longer assumes the dir exists.
        atomic_write_text(
            self.ledger_file,
            "\n".join(json.dumps(t) for t in updated) + ("\n" if updated else ""),
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "positions_checked": len([t for t in trades if t.get("status") == "OPEN"]),
            "positions_closed": len(closed),
            "stale_quote_blocked_count": len(stale_blocked),
            "stale_quote_blocked": stale_blocked,
            "market_state": market_hours.get("state"),
            "market_open": market_open,
            "closed_positions": closed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "PAPER_POSITION_MANAGER_COMPLETE",
        }
