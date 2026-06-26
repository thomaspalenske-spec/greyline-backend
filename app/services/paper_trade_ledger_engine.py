import json
from datetime import datetime
from pathlib import Path
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine
from app.services.dynamic_tp_management_engine import DynamicTPManagementEngine
from app.services.tp_state_tracking_engine import TPStateTrackingEngine
from app.services.thesis_integrity_engine import ThesisIntegrityEngine
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine


class PaperTradeLedgerEngine:
    def __init__(self):
        self.ledger_dir = Path("app/data/paper_trading")
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.ledger_dir / "paper_trade_ledger.jsonl"

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

    def open_trade(
        self,
        symbol="PLTR",
        side="BUY",
        quantity=1,
        entry_price=0.0,
        directional_bias=None,
        option_type=None,
        trade_intent=None,
        bullish_score=None,
        bearish_score=None,
        opposing_score=None,
        direction_confidence=None,
    ):
        entry_thesis = self._entry_thesis_snapshot(symbol)

        trade = {
            "trade_id": f"{symbol}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLedgerEngine",
            "symbol": symbol,
            "side": side,
            "directional_bias": directional_bias,
            "option_type": option_type,
            "trade_intent": trade_intent,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "opposing_score": opposing_score,
            "direction_confidence": direction_confidence,
            "quantity": quantity,
            "entry_price": float(entry_price),
            "exit_price": None,
            "realized_pnl": 0.0,
            "status": "OPEN",
            "execution_mode": "PAPER_ONLY",
            "live_order_placement_attempted": False,
        }

        trade.update(entry_thesis)

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(trade) + "\n")

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_LEDGER_OPENED", trade)

        trade["audit_logged"] = True
        trade["audit_result"] = audit
        return trade

    record_trade = open_trade

    def close_latest(self, symbol="PLTR", exit_price=0.0):
        trades = self._read_all()
        open_trades = [t for t in trades if t.get("symbol") == symbol and t.get("status") == "OPEN"]

        if not open_trades:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "closed": False,
                "reason": "No open paper trade found.",
                "status": "NO_OPEN_PAPER_TRADE",
            }

        trade = open_trades[-1]
        trade["exit_price"] = float(exit_price)

        if trade.get("side") == "BUY":
            trade["realized_pnl"] = round((trade["exit_price"] - trade["entry_price"]) * trade["quantity"], 2)
        else:
            trade["realized_pnl"] = round((trade["entry_price"] - trade["exit_price"]) * trade["quantity"], 2)

        trade["closed_timestamp"] = datetime.utcnow().isoformat()
        trade["status"] = "CLOSED"

        remaining = []
        replaced = False
        for t in trades:
            if t.get("trade_id") == trade.get("trade_id") and not replaced:
                remaining.append(trade)
                replaced = True
            else:
                remaining.append(t)

        with self.ledger_file.open("w") as f:
            for t in remaining:
                f.write(json.dumps(t) + "\n")

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_LEDGER_CLOSED", trade)

        trade["audit_logged"] = True
        trade["audit_result"] = audit
        return trade


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

        base_tp = float(trade.get("take_profit_pct") or 8.0) / 100.0

        tp_pcts = [
            round(base_tp * 0.25, 4),
            round(base_tp * 0.50, 4),
            round(base_tp * 0.75, 4),
            round(base_tp * 1.00, 4),
        ]

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


    def history(self):
        trades = self._read_all()
        open_count = len([t for t in trades if t.get("status") == "OPEN"])
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        total_realized_pnl = round(sum(t.get("realized_pnl", 0.0) for t in closed), 2)

        for trade in trades:
            trade.setdefault("asset_type", "EQUITY")
            trade.setdefault("directional_bias", None)
            trade.setdefault("option_type", None)
            trade.setdefault("trade_intent", None)
            trade.setdefault("bullish_score", None)
            trade.setdefault("bearish_score", None)
            trade.setdefault("opposing_score", None)
            trade.setdefault("direction_confidence", None)
            trade.setdefault("contract_type", "EQUITY")
            trade.setdefault("contract_start_date", trade.get("timestamp"))
            trade.setdefault("contract_expiration_date", None)
            trade.setdefault("initial_contract_days", None)
            trade.setdefault("remaining_contract_days", None)
            trade.setdefault("contract_days_elapsed", None)
            trade.setdefault("contract_status", "NOT_APPLICABLE_EQUITY")
            trade.update(self._tp_ladder(trade))
            trade.update(DynamicTPManagementEngine().evaluate(trade))
            trade.update(TPStateTrackingEngine().evaluate(trade))
            trade.update(ThesisIntegrityEngine().evaluate(trade))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLedgerEngine",
            "trade_count": len(trades),
            "open_trade_count": open_count,
            "closed_trade_count": len(closed),
            "total_realized_pnl": total_realized_pnl,
            "trades": trades,
            "status": "PAPER_TRADE_LEDGER_READY",
        }

    def _read_all(self):
        if not self.ledger_file.exists():
            return []

        trades = []
        with self.ledger_file.open("r") as f:
            for line in f:
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
        return trades
