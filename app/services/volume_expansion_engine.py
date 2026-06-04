from datetime import datetime
from pathlib import Path
import json


class VolumeExpansionEngine:

    def calculate_volume_expansion(self, symbol):
        symbol = symbol.upper().strip()

        storage_dir = Path("app/data/quote_snapshots")

        files = sorted(
            storage_dir.glob(f"{symbol}_*.json"),
            reverse=True
        )

        volumes = []

        for file in files:
            try:
                data = json.loads(file.read_text())

                quote_data = data.get("quote_data", {})
                response_json = quote_data.get("response_json")

                if response_json:
                    quotes = response_json.get("Quotes", [])

                    if quotes:
                        volume = quotes[0].get("Volume")

                        if volume:
                            volumes.append(float(volume))

            except Exception:
                pass

        if len(volumes) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "volume_available": False,
                "valid_volume_points": len(volumes),
                "execution_enabled": False,
                "status": "NOT_ENOUGH_VOLUME_HISTORY"
            }

        latest_volume = volumes[0]
        previous_volume = volumes[1]

        expansion_pct = (
            ((latest_volume - previous_volume) / previous_volume) * 100
            if previous_volume
            else 0
        )

        if expansion_pct > 50:
            score = 95
            state = "INSTITUTIONAL_EXPANSION"
        elif expansion_pct > 20:
            score = 80
            state = "STRONG_EXPANSION"
        elif expansion_pct > 0:
            score = 65
            state = "MODEST_EXPANSION"
        elif expansion_pct > -20:
            score = 50
            state = "NORMAL_VOLUME"
        else:
            score = 25
            state = "VOLUME_CONTRACTION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "volume_available": True,
            "latest_volume": latest_volume,
            "previous_volume": previous_volume,
            "volume_expansion_pct": round(expansion_pct, 2),
            "volume_score": score,
            "volume_state": state,
            "execution_enabled": False,
            "status": "VOLUME_EXPANSION_READY"
        }
