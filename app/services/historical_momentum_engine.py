import json
from datetime import datetime
from pathlib import Path

from app.services.quote_snapshot_comparison_engine import QuoteSnapshotComparisonEngine


class HistoricalMomentumEngine:

    def calculate_momentum(self, symbol):
        symbol = symbol.upper().strip()
        storage_dir = Path("app/data/quote_snapshots")

        files = sorted(
            storage_dir.glob(f"{symbol}_*.json"),
            reverse=True
        )

        prices = []

        comparison_engine = QuoteSnapshotComparisonEngine()

        for file in files:
            data = json.loads(file.read_text())
            price = comparison_engine._extract_price(data)

            if price is not None:
                prices.append(price)

        if len(prices) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "momentum_available": False,
                "valid_price_points": len(prices),
                "execution_enabled": False,
                "status": "NOT_ENOUGH_VALID_PRICE_POINTS"
            }

        latest_price = prices[0]
        previous_price = prices[1]

        price_change = round(latest_price - previous_price, 4)

        percent_change = (
            round((price_change / previous_price) * 100, 4)
            if previous_price
            else 0
        )

        if percent_change > 1:
            momentum_score = 90
            momentum_state = "STRONG_POSITIVE_MOMENTUM"
        elif percent_change > 0.25:
            momentum_score = 75
            momentum_state = "POSITIVE_MOMENTUM"
        elif percent_change > -0.25:
            momentum_score = 55
            momentum_state = "FLAT_MOMENTUM"
        elif percent_change > -1:
            momentum_score = 40
            momentum_state = "NEGATIVE_MOMENTUM"
        else:
            momentum_score = 25
            momentum_state = "STRONG_NEGATIVE_MOMENTUM"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "momentum_available": True,
            "valid_price_points": len(prices),
            "latest_price": latest_price,
            "previous_price": previous_price,
            "price_change": price_change,
            "percent_change": percent_change,
            "momentum_score": momentum_score,
            "momentum_state": momentum_state,
            "execution_enabled": False,
            "status": "HISTORICAL_MOMENTUM_READY"
        }
