import json
from datetime import datetime
from pathlib import Path
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.options_position_sizing_engine import OptionsPositionSizingEngine
from app.services.options_entry_quality_gate_engine import OptionsEntryQualityGateEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class OptionsPaperTradeLedgerEngine:

    def _entry_thesis_snapshot(self, symbol):
        symbol = (symbol or "").upper().strip()
        if not symbol:
            return {
                "entry_thesis_capture_status": "NO_SYMBOL",
            }

        regime = RegimeScoringEngine().score_symbol(symbol)
        risk = RiskStateScoringEngine().score_symbol(symbol)
        ev = ExpectedValueScoringEngine().score_symbol(symbol, regime=regime, risk=risk)

        return {
            "entry_thesis_capture_status": "ENTRY_THESIS_CAPTURED",
            "entry_expected_value_score": ev.get("expected_value_score"),
            "entry_regime_score": regime.get("regime_score"),
            "entry_risk_state_score": risk.get("risk_state_score"),
            "entry_regime": regime.get("regime"),
            "entry_risk_state": risk.get("risk_state"),
            "entry_expected_value_tier": ev.get("expected_value_tier"),
            "entry_thesis_captured_at": datetime.utcnow().isoformat(),
        }

    def __init__(self):
        self.data_dir = Path("app/data/options_paper_trading")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "options_paper_trade_ledger.jsonl"



    def _underlying_quote_snapshot(self, symbol):
        symbol = (symbol or "").upper().strip()
        if not symbol:
            return {
                "underlying_quote_status": "NO_UNDERLYING_SYMBOL",
                "underlying_entry_price": None,
                "underlying_entry_quote_time": None,
            }

        try:
            quote = TradeStationQuoteLiveEngine().get_quote(symbol)
            row = ((quote.get("response_json") or {}).get("Quotes") or [{}])[0]
            price = float(row.get("Last") or row.get("Mid") or row.get("Bid") or row.get("Ask") or 0)
            return {
                "underlying_quote_status": quote.get("status"),
                "underlying_entry_price": price if price > 0 else None,
                "underlying_entry_quote_time": row.get("TradeTime"),
                "underlying_entry_bid": row.get("Bid"),
                "underlying_entry_ask": row.get("Ask"),
                "underlying_entry_last": row.get("Last"),
            }
        except Exception as e:
            return {
                "underlying_quote_status": "UNDERLYING_QUOTE_ERROR",
                "underlying_quote_error": str(e),
                "underlying_entry_price": None,
                "underlying_entry_quote_time": None,
            }

    def _contract_metrics(self, start_raw, expiration_raw):
        from datetime import datetime, timezone

        def parse_dt(value):
            if not value:
                return None
            text = str(value).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text)
            except Exception:
                try:
                    return datetime.fromisoformat(text[:10])
                except Exception:
                    return None

        start = parse_dt(start_raw) or datetime.utcnow()
        expiration = parse_dt(expiration_raw)

        if expiration is None:
            return {
                "initial_contract_days": None,
                "remaining_contract_days": None,
                "contract_days_elapsed": None,
                "contract_status": "EXPIRATION_UNKNOWN",
            }

        now = datetime.utcnow()

        if getattr(start, "tzinfo", None) is not None:
            start = start.replace(tzinfo=None)
        if getattr(expiration, "tzinfo", None) is not None:
            expiration = expiration.replace(tzinfo=None)

        initial = max((expiration.date() - start.date()).days, 0)
        remaining = max((expiration.date() - now.date()).days, 0)
        elapsed = max(initial - remaining, 0)

        if remaining <= 0:
            status = "EXPIRED_OR_EXPIRING"
        elif remaining <= 7:
            status = "MATURITY_WINDOW"
        else:
            status = "ACTIVE_CONTRACT"

        return {
            "initial_contract_days": initial,
            "remaining_contract_days": remaining,
            "contract_days_elapsed": elapsed,
            "contract_status": status,
        }


    def _open_deployed_capital(self):
        if not self.ledger_file.exists():
            return 0.0

        deployed = 0.0
        for line in self.ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                trade = json.loads(line)
            except Exception:
                continue
            if trade.get("status") == "OPEN":
                manager_status = str(trade.get("manager_status") or "")
                pnl_pct = float(trade.get("unrealized_pnl_pct") or 0)
                if manager_status == "OPTION_MARKET_CLOSED_LAST_QUOTE_MARK" and pnl_pct <= -35:
                    continue
                deployed += float(trade.get("estimated_cost") or 0)
        return round(deployed, 2)


    def _closed_realized_pnl(self):
        if not self.ledger_file.exists():
            return 0.0

        realized = 0.0
        for line in self.ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                trade = json.loads(line)
            except Exception:
                continue
            if trade.get("status") == "CLOSED":
                realized += float(trade.get("realized_pnl") or 0)
        return round(realized, 2)

    def record_trade(self, candidate, source="OPTIONS_CYCLE_ENGINE", max_position_pct=0.05, candidate_score=None):
        legs = candidate.get("Legs") or [{}]
        leg = legs[0]

        now = datetime.utcnow()
        underlying = candidate.get("underlying") or candidate.get("Underlying") or leg.get("Underlying") or "NVDA"
        entry_thesis = self._entry_thesis_snapshot(underlying)
        underlying_quote = self._underlying_quote_snapshot(underlying)
        expiration_raw = leg.get("Expiration")
        contract_metrics = self._contract_metrics(now.isoformat(), expiration_raw)

        sizing = OptionsPositionSizingEngine().evaluate(
            account_equity=10000,
            option_ask=float(candidate.get("Ask") or candidate.get("Mid") or candidate.get("Last") or 0),
            max_position_pct=max_position_pct,
        )

        entry_price = float(candidate.get("Ask") or candidate.get("Mid") or candidate.get("Last") or 0)
        entry_quality_gate = OptionsEntryQualityGateEngine().evaluate(
            candidate_score=candidate_score,
            initial_contract_days=contract_metrics.get("initial_contract_days"),
            entry_price=entry_price,
        )

        if entry_quality_gate.get("approved") is not True:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "OPTIONS_PAPER_TRADE_LEDGER",
                "paper_trade_recorded": False,
                "reason": "OPTIONS_ENTRY_QUALITY_GATE_BLOCK",
                "candidate_score": candidate_score,
                "max_position_pct_used": max_position_pct,
                "position_sizing": sizing,
                "entry_quality_gate": entry_quality_gate,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "OPTIONS_PAPER_TRADE_ENTRY_QUALITY_BLOCKED",
            }

        estimated_position_cost = float(sizing.get("estimated_position_cost") or 0)
        deployed_capital = self._open_deployed_capital()
        account_equity = 10000.0
        max_total_deployed_pct = 0.95
        max_total_deployed = round(account_equity * max_total_deployed_pct, 2)
        realized_pnl = self._closed_realized_pnl()
        available_cash = round(account_equity + realized_pnl - deployed_capital, 2)
        available_exposure_capacity = round(max_total_deployed + realized_pnl - deployed_capital, 2)

        if estimated_position_cost > available_exposure_capacity:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "OPTIONS_PAPER_TRADE_LEDGER",
                "paper_trade_recorded": False,
                "reason": "OPTIONS_PORTFOLIO_EXPOSURE_CAP_BLOCK",
                "candidate_score": candidate_score,
                "max_position_pct_used": max_position_pct,
                "position_sizing": sizing,
                "entry_quality_gate": entry_quality_gate,
                "deployed_capital": deployed_capital,
                "account_equity": account_equity,
                "max_total_deployed_pct": max_total_deployed_pct,
                "max_total_deployed": max_total_deployed,
                "available_exposure_capacity": available_exposure_capacity,
                "available_cash": available_cash,
                "realized_pnl": realized_pnl,
                "estimated_position_cost": estimated_position_cost,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "OPTIONS_PAPER_TRADE_EXPOSURE_BLOCKED",
            }

        if estimated_position_cost > available_cash:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "OPTIONS_PAPER_TRADE_LEDGER",
                "paper_trade_recorded": False,
                "reason": "INSUFFICIENT_OPTIONS_PAPER_CASH",
                "candidate_score": candidate_score,
                "max_position_pct_used": max_position_pct,
                "position_sizing": sizing,
                "entry_quality_gate": entry_quality_gate,
                "deployed_capital": deployed_capital,
                "available_cash": available_cash,
                "realized_pnl": realized_pnl,
                "estimated_position_cost": estimated_position_cost,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "OPTIONS_PAPER_TRADE_CASH_BLOCKED",
            }

        if int(sizing.get("recommended_contracts") or 0) <= 0:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "OPTIONS_PAPER_TRADE_LEDGER",
                "paper_trade_recorded": False,
                "reason": sizing.get("sizing_action") or "POSITION_SIZE_ZERO",
                "candidate_score": candidate_score,
            "max_position_pct_used": max_position_pct,
            "position_sizing": sizing,
                "entry_quality_gate": entry_quality_gate,
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "OPTIONS_PAPER_TRADE_SIZE_BLOCKED",
            }

        trade = {
            "timestamp": now.isoformat(),
            "asset_type": "OPTION",
            "contract_type": "OPTION",
            "contract_start_date": now.date().isoformat(),
            "contract_expiration_date": expiration_raw,
            "initial_contract_days": contract_metrics.get("initial_contract_days"),
            "remaining_contract_days": contract_metrics.get("remaining_contract_days"),
            "contract_days_elapsed": contract_metrics.get("contract_days_elapsed"),
            "contract_status": contract_metrics.get("contract_status"),
            "underlying": underlying,
            "option_symbol": leg.get("Symbol"),
            "side": "BUY_TO_OPEN",
            "contracts": sizing.get("recommended_contracts", 1),
            "entry_price": entry_price,
            "entry_mid": float(candidate.get("Mid") or 0),
            "bid": float(candidate.get("Bid") or 0),
            "ask": float(candidate.get("Ask") or 0),
            "strike": float(leg.get("StrikePrice") or 0),
            "expiration": leg.get("Expiration"),
            "option_type": leg.get("OptionType"),
            "delta": float(candidate.get("Delta") or 0),
            "theta": float(candidate.get("Theta") or 0),
            "gamma": float(candidate.get("Gamma") or 0),
            "vega": float(candidate.get("Vega") or 0),
            "implied_volatility": float(candidate.get("ImpliedVolatility") or 0),
            "open_interest": int(candidate.get("DailyOpenInterest") or 0),
            "estimated_cost": sizing.get("estimated_position_cost"),
            "candidate_score": candidate_score,
            "max_position_pct_used": max_position_pct,
            "position_sizing": sizing,
            "entry_quality_gate": entry_quality_gate,
            "source": source,
            "status": "OPEN",
        }

        trade.update(underlying_quote)
        trade.update(entry_thesis)

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(trade) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_PAPER_TRADE_LEDGER",
            "paper_trade_recorded": True,
            "trade": trade,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_PAPER_TRADE_RECORDED",
        }


    def open_position_exists(self, option_symbol):
        if not self.ledger_file.exists():
            return False

        lines = self.ledger_file.read_text().splitlines()

        for line in lines:
            if not line.strip():
                continue

            trade = json.loads(line)

            if (
                trade.get("option_symbol") == option_symbol
                and trade.get("status") == "OPEN"
            ):
                return True

        return False

    def history(self, limit=100):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "OPTIONS_PAPER_TRADE_LEDGER",
                "trade_count": 0,
                "trades": [],
                "status": "NO_OPTIONS_PAPER_TRADES",
            }

        lines = self.ledger_file.read_text().splitlines()
        trades = [json.loads(line) for line in lines[-limit:] if line.strip()]

        for trade in trades:
            metrics = self._contract_metrics(
                trade.get("timestamp"),
                trade.get("expiration") or trade.get("contract_expiration_date"),
            )
            trade["contract_type"] = "OPTION"
            trade["contract_start_date"] = trade.get("contract_start_date") or str(trade.get("timestamp", ""))[:10]
            trade["contract_expiration_date"] = trade.get("contract_expiration_date") or trade.get("expiration")
            trade["initial_contract_days"] = metrics.get("initial_contract_days")
            trade["remaining_contract_days"] = metrics.get("remaining_contract_days")
            trade["contract_days_elapsed"] = metrics.get("contract_days_elapsed")
            trade["contract_status"] = metrics.get("contract_status")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_PAPER_TRADE_LEDGER",
            "trade_count": len(trades),
            "trades": trades,
            "status": "OPTIONS_PAPER_TRADE_HISTORY_READY",
        }
