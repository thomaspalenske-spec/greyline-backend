import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.services.dynamic_tp_management_engine import DynamicTPManagementEngine
from app.services.tp_state_tracking_engine import TPStateTrackingEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.thesis_integrity_engine import ThesisIntegrityEngine


class OptionsAccountDashboardEngine:

    def __init__(self):
        self.starting_equity = 10000.0
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")



    def _float(self, value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _underlying_quote_price(self, symbol):
        if not symbol:
            return None

        result = TradeStationQuoteLiveEngine().get_quote(symbol)
        if result.get("http_status") != 200:
            return None

        quote = (result.get("response_json", {}).get("Quotes") or [{}])[0]
        last = self._float(quote.get("Last"))
        bid = self._float(quote.get("Bid"))
        ask = self._float(quote.get("Ask"))

        if last:
            return round(last, 2)
        if bid and ask:
            return round((bid + ask) / 2, 2)
        return None

    def _estimated_underlying_for_option_price(self, trade, option_target_price, current_underlying):
        current_option = self._float(trade.get("current_price"), 0)
        delta = self._float(trade.get("delta"), 0)
        option_type = str(trade.get("option_type") or "").upper()

        if not current_underlying or not option_target_price or not delta:
            return None

        delta_abs = abs(delta)
        if delta_abs <= 0:
            return None

        option_move = option_target_price - current_option

        if option_type == "PUT":
            estimated = current_underlying - (option_move / delta_abs)
        else:
            estimated = current_underlying + (option_move / delta_abs)

        return round(estimated, 2)

    def _commander_view(self, trade):
        underlying = trade.get("underlying")
        current_underlying = self._underlying_quote_price(underlying)

        entry_contract = self._float(trade.get("entry_price"), 0)
        current_contract = self._float(trade.get("current_price"), 0)
        strike = self._float(trade.get("strike"), 0)
        option_type = str(trade.get("option_type") or "").upper()

        estimated_entry_underlying = self._estimated_underlying_for_option_price(
            trade,
            entry_contract,
            current_underlying,
        )

        if strike and entry_contract:
            if option_type == "PUT":
                breakeven = round(strike - entry_contract, 2)
            else:
                breakeven = round(strike + entry_contract, 2)
        else:
            breakeven = None

        tp_rows = []
        for i in [1, 2, 3]:
            contract_target = self._float(
                trade.get(f"dynamic_tp{i}_price") or trade.get(f"tp{i}_price"),
                None,
            )
            stock_target = self._estimated_underlying_for_option_price(
                trade,
                contract_target,
                current_underlying,
            )

            if current_underlying and stock_target:
                move_dollars = round(stock_target - current_underlying, 2)
                move_pct = round((move_dollars / current_underlying) * 100, 2)
            else:
                move_dollars = None
                move_pct = None

            tp_rows.append({
                "stage": f"TP{i}",
                "contract_target_price": contract_target,
                "estimated_underlying_target_price": stock_target,
                "underlying_move_required_dollars": move_dollars,
                "underlying_move_required_pct": move_pct,
                "hit": trade.get(f"tp{i}_state_hit") or trade.get(f"tp{i}_hit") or False,
            })

        if trade.get("forced_liquidation_required"):
            commander_action = "EXIT_REQUIRED"
            commander_reason = "Expiration governor requires forced liquidation."
        elif trade.get("expiration_governor_state") in ["WATCH", "ELEVATED"]:
            commander_action = "HOLD_WITH_EXPIRATION_CAUTION"
            commander_reason = "Expiration window is approaching; no TP can override the expiration governor."
        elif float(trade.get("unrealized_pnl_pct") or 0) <= -25:
            commander_action = "HOLD_UNDER_PRESSURE"
            commander_reason = "Position is materially underwater, but expiration governor has not forced exit."
        else:
            commander_action = "HOLD"
            commander_reason = "No forced exit condition detected."

        stop_loss_pct = self._float(trade.get("stop_loss_pct"), None)
        if stop_loss_pct is None:
            stop_loss_pct = -50.0

        stop_contract_price = round(current_contract * (1 - (abs(stop_loss_pct) / 100)), 2) if current_contract else None
        stop_underlying = self._estimated_underlying_for_option_price(
            trade,
            stop_contract_price,
            current_underlying,
        )

        if current_underlying and stop_underlying:
            risk_dollars = abs(round(current_underlying - stop_underlying, 2))
            risk_pct = round((risk_dollars / current_underlying) * 100, 2)
        else:
            risk_dollars = None
            risk_pct = None

        risk_box_tp_rows = []
        for row in tp_rows:
            target = row.get("estimated_underlying_target_price")
            if current_underlying and target:
                reward_dollars = abs(round(target - current_underlying, 2))
                reward_pct = round((reward_dollars / current_underlying) * 100, 2)
                rr = round(reward_dollars / risk_dollars, 2) if risk_dollars else None
            else:
                reward_dollars = None
                reward_pct = None
                rr = None

            risk_box_tp_rows.append({
                "stage": row.get("stage"),
                "estimated_underlying_target_price": target,
                "reward_dollars": reward_dollars,
                "reward_pct": reward_pct,
                "risk_reward_ratio": rr,
            })

        return {
            "commander_view": {
                "underlying": underlying,
                "option_symbol": trade.get("option_symbol"),
                "option_type": trade.get("option_type"),
                "strike": strike,
                "expiration": trade.get("expiration"),
                "current_underlying_price": current_underlying,
                "estimated_entry_underlying_price": estimated_entry_underlying,
                "entry_contract_price": entry_contract,
                "current_contract_price": current_contract,
                "breakeven_at_expiration_underlying_price": breakeven,
                "delta_used_for_underlying_estimates": self._float(trade.get("delta"), None),
                "theta_per_contract_per_day": self._float(trade.get("theta"), None),
                "implied_volatility": self._float(trade.get("implied_volatility"), None),
                "days_remaining": trade.get("remaining_contract_days"),
                "days_elapsed": trade.get("contract_days_elapsed"),
                "tp_underlying_ladder": tp_rows,
                "risk_box": {
                    "current_underlying_price": current_underlying,
                    "estimated_entry_underlying_price": estimated_entry_underlying,
                    "estimated_stop_contract_price": stop_contract_price,
                    "estimated_stop_underlying_price": stop_underlying,
                    "underlying_risk_to_stop_dollars": risk_dollars,
                    "underlying_risk_to_stop_pct": risk_pct,
                    "tp_reward_risk": risk_box_tp_rows,
                    "risk_box_note": "Stop underlying price is delta-estimated from the option contract stop price, not applied directly as a percentage of stock price.",
                },
                "commander_action": commander_action,
                "commander_reason": commander_reason,
                "estimation_note": "Underlying TP prices are delta-based estimates, not guarantees. Option value also changes with gamma, theta, vega, and implied volatility.",
            }
        }

    def _contract_metrics(self, trade):
        start_raw = trade.get("timestamp")
        exp_raw = trade.get("expiration")

        if not exp_raw:
            return {
                "contract_start_date": start_raw,
                "contract_expiration_date": None,
                "initial_contract_days": None,
                "remaining_contract_days": None,
                "contract_days_elapsed": None,
                "contract_status": "MISSING_EXPIRATION",
            }

        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)

            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)

            initial_days = max((exp_dt.date() - start_dt.date()).days, 0)
            remaining_days = max((exp_dt.date() - now_dt.date()).days, 0)
            elapsed_days = max((now_dt.date() - start_dt.date()).days, 0)

            if remaining_days <= 0:
                status = "EXPIRED"
            elif remaining_days == 1:
                status = "EXPIRES_TOMORROW"
            elif remaining_days <= 5:
                status = "EXPIRATION_WINDOW"
            else:
                status = "ACTIVE"

            return {
                "contract_start_date": start_raw,
                "contract_expiration_date": exp_raw,
                "initial_contract_days": initial_days,
                "remaining_contract_days": remaining_days,
                "contract_days_elapsed": elapsed_days,
                "contract_status": status,
            }

        except Exception as e:
            return {
                "contract_start_date": start_raw,
                "contract_expiration_date": exp_raw,
                "initial_contract_days": None,
                "remaining_contract_days": None,
                "contract_days_elapsed": None,
                "contract_status": "CONTRACT_DATE_PARSE_ERROR",
                "contract_error": str(e),
            }



    def _tp_ladder(self, trade):
        entry = float(trade.get("entry_price") or 0)
        current = float(trade.get("current_price") or 0)

        if entry <= 0:
            return {
                "tp_model": "UNAVAILABLE",
                "tp1_price": None,
                "tp2_price": None,
                "tp3_price": None,
                "tp4_price": None,
            }

        tp_pcts = [0.25, 0.50, 0.75, 1.00]

        ladder = {
            "tp_model": "FOUR_STAGE_DYNAMIC_TP_LADDER_WITH_DYNAMIC_DIVESTMENT_ADVISORY",
            "tp1_exit_pct": "DYNAMIC",
            "tp2_exit_pct": "DYNAMIC",
            "tp3_exit_pct": "DYNAMIC",
            "tp4_exit_pct": "RUNNER_REMAINDER",
            "tp4_runner": True,
            "fixed_25pct_exit_model_replaced": True,
            "divestment_model": "DYNAMIC_DIVESTMENT_ADVISORY",
            "tp_pct_fields_mean": "PRICE_TARGET_LEVELS_NOT_EXIT_PERCENTAGES",
        }

        for i, pct in enumerate(tp_pcts, start=1):
            price = round(entry * (1 + pct), 2)
            ladder[f"tp{i}_pct"] = round(pct * 100, 2)  # Backward compatibility: target level, not exit size.
            ladder[f"tp{i}_target_pct"] = round(pct * 100, 2)
            ladder[f"tp{i}_target_pct_type"] = "PRICE_TARGET_LEVEL_NOT_DIVESTMENT_SIZE"
            ladder[f"tp{i}_price"] = price
            ladder[f"tp{i}_hit"] = bool(current >= price) if current else False
            ladder[f"tp{i}_distance_dollars"] = round(price - current, 2) if current else None
            ladder[f"tp{i}_distance_pct"] = round(((price - current) / current) * 100, 2) if current else None

        return ladder

    def _expiration_governor(self, trade):
        exp_raw = trade.get("expiration")

        if not exp_raw:
            return {
                "expiration_governor_state": "NOT_APPLICABLE",
                "forced_liquidation_required": False,
                "forced_liquidation_deadline": None,
                "expiration_override_rule": "NO_OPTION_HELD_THROUGH_EXPIRATION",
                "hold_through_expiration_allowed": False,
            }

        try:
            exp_dt = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))

            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)

            now_dt = datetime.now(timezone.utc)
            remaining_days = max((exp_dt.date() - now_dt.date()).days, 0)

            forced_date = exp_dt.date() - timedelta(days=1)
            forced_liquidation_deadline = f"{forced_date}T15:00:00-04:00"

            if remaining_days <= 0:
                state = "FORCED_EXIT_REQUIRED_EXPIRATION_DAY"
                required = True
            elif remaining_days == 1:
                state = "FORCED_EXIT_WINDOW"
                required = True
            elif remaining_days <= 3:
                state = "ELEVATED"
                required = False
            elif remaining_days <= 5:
                state = "WATCH"
                required = False
            else:
                state = "NORMAL"
                required = False

            return {
                "expiration_governor_state": state,
                "forced_liquidation_required": required,
                "forced_liquidation_deadline": forced_liquidation_deadline,
                "expiration_override_rule": "NO_TP_OR_RUNNER_CAN_OVERRIDE_EXPIRATION_GOVERNOR",
                "hold_through_expiration_allowed": False,
            }

        except Exception as e:
            return {
                "expiration_governor_state": "EXPIRATION_GOVERNOR_PARSE_ERROR",
                "forced_liquidation_required": False,
                "forced_liquidation_deadline": None,
                "expiration_override_rule": "NO_OPTION_HELD_THROUGH_EXPIRATION",
                "hold_through_expiration_allowed": False,
                "expiration_governor_error": str(e),
            }


    def get_dashboard(self):
        trades = []

        if self.ledger_file.exists():
            trades = [
                json.loads(line)
                for line in self.ledger_file.read_text().splitlines()
                if line.strip()
            ]

        open_trades = []
        for t in trades:
            if t.get("status") == "OPEN":
                enriched = dict(t)
                enriched.update(self._contract_metrics(enriched))
                enriched.update(self._tp_ladder(enriched))
                enriched.update(DynamicTPManagementEngine().evaluate(enriched))
                enriched.update(TPStateTrackingEngine().evaluate(enriched))
                enriched.update(self._expiration_governor(enriched))
                enriched.update(ThesisIntegrityEngine().evaluate(enriched))
                enriched.update(self._commander_view(enriched))
                open_trades.append(enriched)
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]

        realized_pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed_trades), 2)
        unrealized_pnl = round(sum(float(t.get("unrealized_pnl") or 0) for t in open_trades), 2)

        deployable_open_trades = [
            t for t in open_trades
            if not (
                str(t.get("manager_status") or "") == "OPTION_MARKET_CLOSED_LAST_QUOTE_MARK"
                and float(t.get("unrealized_pnl_pct") or 0) <= -35
            )
        ]
        deployed_capital = round(sum(float(t.get("estimated_cost") or 0) for t in deployable_open_trades), 2)
        open_position_value = round(deployed_capital + unrealized_pnl, 2)
        cash_on_hand = round(self.starting_equity + realized_pnl - deployed_capital, 2)
        buying_power_remaining = cash_on_hand
        capital_deployed_pct = round((deployed_capital / self.starting_equity) * 100, 2) if self.starting_equity else 0

        current_equity = round(cash_on_hand + open_position_value, 2)

        wins = [t for t in closed_trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in closed_trades if float(t.get("realized_pnl") or 0) < 0]

        win_rate_pct = round((len(wins) / len(closed_trades)) * 100, 2) if closed_trades else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "account_type": "OPTIONS_PAPER_TRADING",
            "starting_equity": self.starting_equity,
            "current_equity": current_equity,
            "cash_on_hand": cash_on_hand,
            "open_position_value": open_position_value,
            "deployed_capital": deployed_capital,
            "buying_power_remaining": buying_power_remaining,
            "capital_deployed_pct": capital_deployed_pct,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_return_pct": round(((current_equity - self.starting_equity) / self.starting_equity) * 100, 2),
            "option_trade_count": len(trades),
            "open_option_trade_count": len(open_trades),
            "closed_option_trade_count": len(closed_trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": win_rate_pct,
            "open_positions": open_trades,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_ACCOUNT_DASHBOARD_READY",
        }
