import json
from datetime import datetime
from pathlib import Path


class PortfolioExposureEngine:
    def __init__(self):
        self.equity_ledger = Path("app/data/paper_trading/paper_trade_ledger.jsonl")
        self.option_ledger = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def _read_jsonl(self, path):
        if not path.exists():
            return []

        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return rows

    def _sector(self, symbol):
        symbol = (symbol or "").upper().strip()

        sector_map = {
            "XLE": "ENERGY",
            "XLF": "FINANCIALS",
            "XLU": "UTILITIES",
            "XLK": "TECHNOLOGY",
            "XLY": "CONSUMER_DISCRETIONARY",
            "XLP": "CONSUMER_STAPLES",
            "XLI": "INDUSTRIALS",
            "XLV": "HEALTHCARE",
            "XLB": "MATERIALS",
            "XLRE": "REAL_ESTATE",
            "XLC": "COMMUNICATIONS",
            "QQQ": "TECH_GROWTH",
            "SPY": "BROAD_MARKET",
            "IWM": "SMALL_CAP",
            "NVDA": "TECHNOLOGY",
            "AMD": "TECHNOLOGY",
            "AVGO": "TECHNOLOGY",
            "MSFT": "TECHNOLOGY",
            "META": "COMMUNICATIONS",
            "AMZN": "CONSUMER_DISCRETIONARY",
            "TSM": "TECHNOLOGY",
            "PLTR": "TECHNOLOGY",
        }

        return sector_map.get(symbol, "UNKNOWN")

    def _notional(self, trade):
        qty = float(trade.get("quantity") or trade.get("contracts") or 0)
        price = float(
            trade.get("current_price")
            or trade.get("entry_price")
            or 0
        )

        multiplier = 100 if trade.get("asset_type") == "OPTION" else 1
        return round(abs(qty * price * multiplier), 2)

    def evaluate(self):
        equity_rows = self._read_jsonl(self.equity_ledger)
        option_rows = self._read_jsonl(self.option_ledger)

        open_positions = []

        for row in equity_rows:
            if row.get("status") == "OPEN":
                symbol = row.get("symbol")
                open_positions.append({
                    "symbol": symbol,
                    "asset_type": row.get("asset_type", "EQUITY"),
                    "sector": self._sector(symbol),
                    "notional": self._notional(row),
                    "directional_bias": row.get("directional_bias"),
                    "status": row.get("status"),
                })

        for row in option_rows:
            if row.get("status") == "OPEN":
                symbol = row.get("underlying") or row.get("symbol")
                open_positions.append({
                    "symbol": symbol,
                    "asset_type": "OPTION",
                    "sector": self._sector(symbol),
                    "notional": self._notional(row),
                    "directional_bias": row.get("directional_bias"),
                    "status": row.get("status"),
                })

        total_notional = round(sum(p["notional"] for p in open_positions), 2)

        sector_exposure = {}
        for p in open_positions:
            sector = p["sector"]
            sector_exposure.setdefault(sector, 0.0)
            sector_exposure[sector] += p["notional"]

        sector_exposure = {
            k: {
                "notional": round(v, 2),
                "pct_of_portfolio": round((v / total_notional) * 100, 2) if total_notional else 0,
            }
            for k, v in sorted(sector_exposure.items())
        }

        max_sector_pct = max(
            [v["pct_of_portfolio"] for v in sector_exposure.values()],
            default=0,
        )

        if max_sector_pct >= 50:
            concentration_risk = "HIGH"
        elif max_sector_pct >= 35:
            concentration_risk = "ELEVATED"
        elif max_sector_pct >= 20:
            concentration_risk = "MODERATE"
        else:
            concentration_risk = "LOW"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioExposureEngine",
            "open_position_count": len(open_positions),
            "total_notional": total_notional,
            "sector_exposure": sector_exposure,
            "max_sector_exposure_pct": max_sector_pct,
            "concentration_risk": concentration_risk,
            "positions": open_positions,
            "status": "PORTFOLIO_EXPOSURE_READY",
        }
