import json
from datetime import datetime
from pathlib import Path


class PositionAlertAckEngine:
    """
    Keeps stop-loss / forced-exit closed positions visible until acknowledged.
    Uses the existing options paper ledger as the source of truth.
    """

    STOP_ALERT_REASONS = [
        "STOP_LOSS",
        "OPTIONS_STOP_LOSS",
        "GREYLINE_DYNAMIC_STOP_LOSS",
        "TP1_PROTECTIVE_STOP",
        "EXPIRATION_GOVERNOR_EXIT",
        "OPTIONS_MATURITY_PROTECTION",
        "OPTIONS_MATURITY_PROTECTION_24HR",
    ]

    def __init__(self):
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def _read(self):
        if not self.ledger_file.exists():
            return []
        rows = []
        for line in self.ledger_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows

    def _write(self, rows):
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_file.write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
        )

    def _trade_id(self, trade):
        return (
            trade.get("trade_id")
            or trade.get("option_symbol")
            or trade.get("symbol")
            or ""
        )

    def _is_alert_reason(self, reason):
        r = str(reason or "").upper()
        return any(token in r for token in self.STOP_ALERT_REASONS)

    def unacknowledged_alerts(self):
        alerts = []
        for trade in self._read():
            if trade.get("status") != "CLOSED":
                continue
            if not self._is_alert_reason(trade.get("exit_reason")):
                continue
            if trade.get("operator_acknowledged") is True:
                continue

            alerts.append({
                "trade_id": self._trade_id(trade),
                "symbol": trade.get("underlying") or trade.get("symbol"),
                "option_symbol": trade.get("option_symbol") or trade.get("symbol"),
                "option_type": trade.get("option_type"),
                "exit_reason": trade.get("exit_reason"),
                "entry_price": trade.get("entry_price"),
                "exit_price": trade.get("exit_price"),
                "realized_pnl": trade.get("realized_pnl"),
                "realized_pnl_pct": trade.get("realized_pnl_pct"),
                "exit_timestamp": trade.get("exit_timestamp") or trade.get("closed_timestamp"),
                "acknowledged": False,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PositionAlertAckEngine",
            "alert_count": len(alerts),
            "alerts": alerts,
            "status": "POSITION_ALERTS_READY",
        }

    def acknowledge(self, trade_id):
        rows = self._read()
        matched = False

        for trade in rows:
            if self._trade_id(trade) == trade_id:
                trade["operator_acknowledged"] = True
                trade["operator_acknowledged_at"] = datetime.utcnow().isoformat()
                matched = True

        if matched:
            self._write(rows)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_id": trade_id,
            "acknowledged": matched,
            "status": "POSITION_ALERT_ACKNOWLEDGED" if matched else "POSITION_ALERT_NOT_FOUND",
        }
