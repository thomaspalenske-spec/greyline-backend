import json
from datetime import datetime, timedelta, time, timezone
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.market_hours_engine import MarketHoursEngine


class OptionsPositionManagerEngine:

    def __init__(self):
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def _parse_expiration(self, expiration_value):
        if not expiration_value:
            return None
        raw = str(expiration_value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=None)
        except Exception:
            return None

    def _parse_trade_time(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _last_market_opportunity(self, expiration_dt):
        if expiration_dt is None:
            return None
        return datetime.combine(expiration_dt.date(), time(16, 0))

    def _maturity_liquidation_required(self, expiration_value):
        expiration_dt = self._parse_expiration(expiration_value)
        last_market_opportunity = self._last_market_opportunity(expiration_dt)

        if last_market_opportunity is None:
            return {
                "required": False,
                "reason": "EXPIRATION_UNAVAILABLE",
                "last_market_opportunity": None,
                "forced_liquidation_deadline": None,
            }

        forced_liquidation_deadline = last_market_opportunity - timedelta(hours=24)
        now = datetime.utcnow()

        return {
            "required": now >= forced_liquidation_deadline,
            "reason": (
                "WITHIN_24_HOURS_OF_LAST_MARKET_OPPORTUNITY"
                if now >= forced_liquidation_deadline
                else "MATURITY_WINDOW_NOT_REACHED"
            ),
            "last_market_opportunity": last_market_opportunity.isoformat(),
            "forced_liquidation_deadline": forced_liquidation_deadline.isoformat(),
        }

    def manage_open_positions(self):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "positions_checked": 0,
                "positions_closed": 0,
                "stale_quote_blocked_count": 0,
                "status": "NO_OPTIONS_PAPER_LEDGER",
            }

        trades = [
            json.loads(line)
            for line in self.ledger_file.read_text().splitlines()
            if line.strip()
        ]

        updated = []
        checked = 0
        closed = []
        stale_blocked = []
        market_hours = MarketHoursEngine().status()
        market_open = bool(market_hours.get('is_regular_session'))

        for trade in trades:
            if trade.get("status") != "OPEN":
                updated.append(trade)
                continue

            checked += 1
            option_symbol = trade.get("option_symbol")
            entry_price = float(trade.get("entry_price") or 0)
            contracts = int(trade.get("contracts") or 0)

            quote = TradeStationQuoteLiveEngine().get_quote(option_symbol)
            quote_row = ((quote.get("response_json") or {}).get("Quotes") or [{}])[0]

            try:
                current_price = float(
                    quote_row.get("Last")
                    or quote_row.get("Mid")
                    or quote_row.get("Bid")
                    or 0
                )
            except Exception:
                current_price = 0.0

            trade_time_raw = quote_row.get("TradeTime")
            trade_time = self._parse_trade_time(trade_time_raw)
            quote_age_seconds = None if trade_time is None else round((datetime.now(timezone.utc) - trade_time).total_seconds(), 2)
            market_flags = quote_row.get("MarketFlags") or {}
            is_delayed = bool(market_flags.get("IsDelayed"))

            maturity_rule = self._maturity_liquidation_required(trade.get("expiration"))
            trade["maturity_rule"] = maturity_rule

            if current_price <= 0 or entry_price <= 0:
                trade["manager_status"] = "OPTION_PRICE_UNAVAILABLE"
                trade["last_manager_block_reason"] = "OPTION_PRICE_UNAVAILABLE"
                trade["last_managed_at"] = datetime.utcnow().isoformat()
                updated.append(trade)
                continue

            if market_open and (is_delayed or quote_age_seconds is None or quote_age_seconds > 900):
                trade["manager_status"] = "OPTION_STALE_QUOTE_BLOCKED"
                trade["last_manager_block_reason"] = "FRESH_NON_DELAYED_OPTION_QUOTE_REQUIRED"
                trade["last_quote_trade_time"] = trade_time_raw
                trade["last_quote_age_seconds"] = quote_age_seconds
                trade["last_quote_is_delayed"] = is_delayed
                trade["last_manager_checked_at"] = datetime.utcnow().isoformat()
                stale_blocked.append({
                    "option_symbol": option_symbol,
                    "trade_time": trade_time_raw,
                    "quote_age_seconds": quote_age_seconds,
                    "is_delayed": is_delayed,
                })
                updated.append(trade)
                continue

            pnl = round((current_price - entry_price) * contracts * 100, 2)
            pnl_pct = round(((current_price / entry_price) - 1) * 100, 2)

            if not market_open:
                trade["current_price"] = current_price
                trade["unrealized_pnl"] = pnl
                trade["unrealized_pnl_pct"] = pnl_pct
                trade["manager_status"] = "OPTION_MARKET_CLOSED_LAST_QUOTE_MARK"
                trade["market_state"] = market_hours.get("state")
                trade["last_quote_trade_time"] = trade_time_raw
                trade["last_quote_age_seconds"] = quote_age_seconds
                trade["last_quote_is_delayed"] = is_delayed
                trade["last_manager_checked_at"] = datetime.utcnow().isoformat()
                updated.append(trade)
                continue

            trade["current_price"] = current_price
            trade["unrealized_pnl"] = pnl
            trade["unrealized_pnl_pct"] = pnl_pct
            trade["last_quote_trade_time"] = trade_time_raw
            trade["last_quote_age_seconds"] = quote_age_seconds
            trade["last_quote_is_delayed"] = is_delayed
            trade["last_managed_at"] = datetime.utcnow().isoformat()
            trade["manager_status"] = "OPTION_POSITION_UPDATED_FRESH_QUOTE"

            if maturity_rule.get("required") is True:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = pnl
                trade["realized_pnl_pct"] = pnl_pct
                trade["exit_reason"] = "OPTIONS_MATURITY_PROTECTION_24HR"
                closed.append(trade)
            elif pnl_pct >= 50:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = pnl
                trade["realized_pnl_pct"] = pnl_pct
                trade["exit_reason"] = "OPTIONS_TAKE_PROFIT_50_PCT"
                closed.append(trade)
            elif pnl_pct <= -35:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = pnl
                trade["realized_pnl_pct"] = pnl_pct
                trade["exit_reason"] = "OPTIONS_STOP_LOSS_35_PCT"
                closed.append(trade)

            updated.append(trade)

        self.ledger_file.write_text(
            "\n".join(json.dumps(t) for t in updated) + ("\n" if updated else "")
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_POSITION_MANAGER",
            "positions_checked": checked,
            "positions_closed": len(closed),
            "stale_quote_blocked_count": len(stale_blocked),
            "stale_quote_blocked": stale_blocked,
            "market_state": market_hours.get("state"),
            "market_open": market_open,
            "closed_positions": closed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_POSITION_MANAGER_COMPLETE",
        }
