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
            try:
                data = json.loads(file.read_text())
                price = comparison_engine._extract_price(data)

                if price is not None:
                    prices.append(price)
            except Exception:
                pass

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

        def pct_change_from(index):
            if len(prices) <= index or prices[index] == 0:
                return None
            return round(((latest_price - prices[index]) / prices[index]) * 100, 4)

        short_term_pct = pct_change_from(1)
        intermediate_pct = pct_change_from(5)
        long_term_pct = pct_change_from(10)

        available_changes = [
            value for value in [
                short_term_pct,
                intermediate_pct,
                long_term_pct
            ]
            if value is not None
        ]

        average_momentum_pct = (
            round(sum(available_changes) / len(available_changes), 4)
            if available_changes
            else 0
        )

        if average_momentum_pct > 1:
            momentum_score = 90
            momentum_state = "STRONG_POSITIVE_MOMENTUM"
        elif average_momentum_pct > 0.25:
            momentum_score = 75
            momentum_state = "POSITIVE_MOMENTUM"
        elif average_momentum_pct > -0.25:
            momentum_score = 55
            momentum_state = "FLAT_MOMENTUM"
        elif average_momentum_pct > -1:
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
            "short_term_percent_change": short_term_pct,
            "intermediate_percent_change": intermediate_pct,
            "long_term_percent_change": long_term_pct,
            "average_momentum_percent": average_momentum_pct,
            "momentum_score": momentum_score,
            "momentum_state": momentum_state,
            "execution_enabled": False,
            "status": "HISTORICAL_MOMENTUM_READY"
        }
