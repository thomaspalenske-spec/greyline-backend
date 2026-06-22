import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.services.dynamic_tp_management_engine import DynamicTPManagementEngine
from app.services.tp_state_tracking_engine import TPStateTrackingEngine


class OptionsAccountDashboardEngine:

    def __init__(self):
        self.starting_equity = 10000.0
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")


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
            "tp_model": "FOUR_STAGE_DYNAMIC_TP_LADDER",
            "tp1_exit_pct": 25,
            "tp2_exit_pct": 25,
            "tp3_exit_pct": 25,
            "tp4_exit_pct": 25,
            "tp4_runner": True,
        }

        for i, pct in enumerate(tp_pcts, start=1):
            price = round(entry * (1 + pct), 2)
            ladder[f"tp{i}_pct"] = round(pct * 100, 2)
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
                open_trades.append(enriched)
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]

        realized_pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed_trades), 2)
        unrealized_pnl = round(sum(float(t.get("unrealized_pnl") or 0) for t in open_trades), 2)

        current_equity = round(self.starting_equity + realized_pnl + unrealized_pnl, 2)

        wins = [t for t in closed_trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in closed_trades if float(t.get("realized_pnl") or 0) < 0]

        win_rate_pct = round((len(wins) / len(closed_trades)) * 100, 2) if closed_trades else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "account_type": "OPTIONS_PAPER_TRADING",
            "starting_equity": self.starting_equity,
            "current_equity": current_equity,
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
