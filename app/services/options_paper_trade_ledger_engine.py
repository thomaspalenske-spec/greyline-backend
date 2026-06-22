import json
from datetime import datetime
from pathlib import Path
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine


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

    def record_trade(self, candidate, source="OPTIONS_CYCLE_ENGINE"):
        legs = candidate.get("Legs") or [{}]
        leg = legs[0]

        now = datetime.utcnow()
        underlying = candidate.get("underlying") or candidate.get("Underlying") or leg.get("Underlying") or "NVDA"
        entry_thesis = self._entry_thesis_snapshot(underlying)
        expiration_raw = leg.get("Expiration")
        contract_metrics = self._contract_metrics(now.isoformat(), expiration_raw)

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
            "contracts": 1,
            "entry_price": float(candidate.get("Ask") or candidate.get("Mid") or candidate.get("Last") or 0),
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
            "estimated_cost": round(float(candidate.get("Ask") or candidate.get("Mid") or 0) * 100, 2),
            "source": source,
            "status": "OPEN",
        }

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
