from datetime import datetime

from app.services.historical_momentum_engine import HistoricalMomentumEngine


class SectorRotationEngine:

    def evaluate_sectors(self):
        sector_map = {
            "XLK": "Technology",
            "SMH": "Semiconductors",
            "XLF": "Financials",
            "XLE": "Energy",
            "XLI": "Industrials",
            "XLV": "Healthcare",
            "XLP": "Consumer Staples",
            "XLU": "Utilities",
            "XLY": "Consumer Discretionary",
            "XLB": "Materials",
            "IWM": "Small Caps",
            "QQQ": "Nasdaq 100",
            "SPY": "S&P 500",
            "IBIT": "Bitcoin ETF",
            "ETHE": "Ethereum ETF"
        }

        sectors = []

        for symbol, name in sector_map.items():
            momentum = HistoricalMomentumEngine().calculate_momentum(symbol)

            sectors.append({
                "symbol": symbol,
                "sector": name,
                "momentum_score": momentum.get("momentum_score", 0),
                "average_momentum_percent": momentum.get("average_momentum_percent"),
                "momentum_state": momentum.get("momentum_state"),
                "execution_enabled": False
            })

        sectors.sort(
            key=lambda item: item.get("momentum_score", 0),
            reverse=True
        )

        top_sector = sectors[0] if sectors else None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sectors_ranked": len(sectors),
            "top_sector": top_sector,
            "rankings": sectors,
            "execution_enabled": False,
            "status": "SECTOR_ROTATION_READY"
        }
