from datetime import datetime
from pathlib import Path
import json


class BattlefieldHistoryEngine:
    _path = Path("app/data/battlefield_history.jsonl")

    @classmethod
    def record(cls, battlefield):
        cls._path.parent.mkdir(parents=True, exist_ok=True)

        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "market_bias": battlefield.get("market_bias"),
            "symbols_scored": battlefield.get("symbols_scored"),
        }

        side_map = {
            "best_call": ((battlefield.get("calls") or {}).get("best") or {}),
            "best_put": ((battlefield.get("puts") or {}).get("best") or {}),
        }

        for side, item in side_map.items():
            row[side] = {
                "symbol": item.get("symbol"),
                "result": item.get("result"),
                "composite_score": item.get("composite_score"),
                "directional_bias": item.get("directional_bias"),
                "direction_confidence": item.get("direction_confidence"),
                "liquidity_score": item.get("liquidity_score"),
                "setup_score": item.get("setup_score"),
                "option_type": item.get("option_type"),
            }

        with open(cls._path, "a") as f:
            f.write(json.dumps(row) + "\n")

        return {
            "recorded": True,
            "path": str(cls._path),
            "status": "BATTLEFIELD_HISTORY_RECORDED",
        }

    @classmethod
    def load(cls, limit=500):
        if not cls._path.exists():
            return []

        rows = []

        with open(cls._path) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass

        return rows[-limit:]
