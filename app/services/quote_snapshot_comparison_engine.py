import json
from datetime import datetime
from pathlib import Path


class QuoteSnapshotComparisonEngine:

    def _extract_price(self, snapshot):
        quote_data = snapshot.get("quote_data", {})

        response_json = quote_data.get("response_json")
        if response_json:
            quotes = response_json.get("Quotes", [])
            if quotes:
                quote = quotes[0]
                for key in ["Last", "Close", "Bid", "Ask"]:
                    value = quote.get(key)
                    if value not in [None, ""]:
                        return float(value)

        preview = quote_data.get("response_preview")
        if preview:
            try:
                parsed = json.loads(preview)
                quotes = parsed.get("Quotes", [])
                if quotes:
                    quote = quotes[0]
                    for key in ["Last", "Close", "Bid", "Ask"]:
                        value = quote.get(key)
                        if value not in [None, ""]:
                            return float(value)
            except Exception:
                return None

        return None

    def compare_latest_two(self, symbol):
        symbol = symbol.upper().strip()
        storage_dir = Path("app/data/quote_snapshots")

        files = sorted(storage_dir.glob(f"{symbol}_*.json"), reverse=True)

        valid = []

        for file in files:
            data = json.loads(file.read_text())
            price = self._extract_price(data)
            if price is not None:
                valid.append((file, data, price))

        if len(valid) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "comparison_available": False,
                "snapshots_found": len(files),
                "valid_snapshots_found": len(valid),
                "execution_enabled": False,
                "status": "NOT_ENOUGH_VALID_SNAPSHOTS"
            }

        latest_file, latest, latest_price = valid[0]
        previous_file, previous, previous_price = valid[1]

        price_change = round(latest_price - previous_price, 4)

        percent_change = (
            round((price_change / previous_price) * 100, 4)
            if previous_price
            else 0
        )

        direction = "UP" if price_change > 0 else "DOWN" if price_change < 0 else "FLAT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "comparison_available": True,
            "snapshots_found": len(files),
            "valid_snapshots_found": len(valid),
            "latest_price": latest_price,
            "previous_price": previous_price,
            "price_change": price_change,
            "percent_change": percent_change,
            "direction": direction,
            "execution_enabled": False,
            "status": "QUOTE_SNAPSHOT_COMPARISON_READY"
        }
