import json
from datetime import datetime
from pathlib import Path


class OptionsPaperTradeLedgerEngine:

    def __init__(self):
        self.data_dir = Path("app/data/options_paper_trading")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "options_paper_trade_ledger.jsonl"

    def record_trade(self, candidate, source="OPTIONS_CYCLE_ENGINE"):
        legs = candidate.get("Legs") or [{}]
        leg = legs[0]

        trade = {
            "timestamp": datetime.utcnow().isoformat(),
            "asset_type": "OPTION",
            "underlying": "NVDA",
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

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_PAPER_TRADE_LEDGER",
            "trade_count": len(trades),
            "trades": trades,
            "status": "OPTIONS_PAPER_TRADE_HISTORY_READY",
        }
