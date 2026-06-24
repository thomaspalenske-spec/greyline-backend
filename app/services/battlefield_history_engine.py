from datetime import datetime
from pathlib import Path
import json


class BattlefieldHistoryEngine:
    _path = Path("app/data/battlefield_history.jsonl")

    @classmethod
    def _candidate(cls, battlefield, top_key, nested_key):
        # Supports both:
        # 1) raw battlefield: battlefield["puts"]["best"]
        # 2) summary cache: battlefield["best_put"]
        item = battlefield.get(top_key) or {}
        if item.get("symbol") or item.get("composite_score") or item.get("score"):
            return item

        return ((battlefield.get(nested_key) or {}).get("best") or {})

    @classmethod
    def record(cls, battlefield):
        cls._path.parent.mkdir(parents=True, exist_ok=True)

        best_call = cls._candidate(battlefield, "best_call", "calls")
        best_put = cls._candidate(battlefield, "best_put", "puts")

        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "battlefield_health": battlefield.get("battlefield_health"),
            "battlefield_health_reason": battlefield.get("battlefield_health_reason"),
            "market_bias": battlefield.get("market_bias"),
            "symbols_scored": battlefield.get("symbols_scored"),
            "ready_call_count": battlefield.get("ready_call_count") or (battlefield.get("calls") or {}).get("ready_count"),
            "ready_put_count": battlefield.get("ready_put_count") or (battlefield.get("puts") or {}).get("ready_count"),
            "best_call": cls._normalize(best_call),
            "best_put": cls._normalize(best_put),
        }

        with open(cls._path, "a") as f:
            f.write(json.dumps(row) + "\n")

        return {
            "recorded": True,
            "path": str(cls._path),
            "status": "BATTLEFIELD_HISTORY_RECORDED",
        }


    @classmethod
    def _signal_age_days(cls, symbol, option_type):
        if not symbol or not cls._path.exists():
            return 0

        first_seen = None
        now = datetime.utcnow()

        with open(cls._path) as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue

                for key in ["best_call", "best_put"]:
                    item = row.get(key) or {}
                    if item.get("symbol") == symbol and item.get("option_type") == option_type:
                        first_seen = row.get("timestamp")
                        break

                if first_seen:
                    break

        if not first_seen:
            return 0

        try:
            first_dt = datetime.fromisoformat(first_seen)
            return round(max((now - first_dt).total_seconds(), 0) / 86400, 4)
        except Exception:
            return 0

    @staticmethod
    def _normalize(item):
        return {
            "symbol": item.get("symbol"),
            "result": item.get("result"),
            "composite_score": item.get("composite_score") if item.get("composite_score") is not None else item.get("score"),
            "directional_bias": item.get("directional_bias"),
            "direction_confidence": item.get("direction_confidence"),
            "liquidity_score": item.get("liquidity_score"),
            "setup_score": item.get("setup_score"),
            "option_type": item.get("option_type"),
            "signal_age_days": BattlefieldHistoryEngine._signal_age_days(
                item.get("symbol"),
                item.get("option_type"),
            ),
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

    def history(self, limit=500):
        return self.load(limit=limit)
