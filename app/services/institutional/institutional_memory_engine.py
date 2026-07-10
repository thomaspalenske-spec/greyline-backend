import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class InstitutionalMemoryEngine:
    DATA_DIR = Path("app/data/institutional_memory")

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _symbol(symbol: str) -> str:
        value = (symbol or "").upper().strip()
        if not value:
            raise ValueError("symbol is required")
        return value

    def _path(self, symbol: str) -> Path:
        return self.DATA_DIR / f"{self._symbol(symbol)}.jsonl"

    def record(
        self,
        symbol: str,
        snapshot: Dict[str, Any],
        source: str = "INSTITUTIONAL_INTELLIGENCE_ENGINE",
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be a dictionary")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "source": source,
            "snapshot": snapshot,
        }

        path = self._path(symbol)

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

        return {
            "recorded": True,
            "symbol": symbol,
            "path": str(path),
            "status": "INSTITUTIONAL_MEMORY_RECORDED",
        }

    def history(
        self,
        symbol: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        path = self._path(symbol)

        if not path.exists():
            return []

        records: List[Dict[str, Any]] = []

        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()

                if not raw:
                    continue

                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if isinstance(value, dict):
                    records.append(value)

        limit = max(1, int(limit))
        return records[-limit:]

    def latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        records = self.history(symbol, limit=1)
        return records[-1] if records else None

    def summary(
        self,
        symbol: str,
        limit: int = 100,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)
        records = self.history(symbol, limit=limit)

        scores = []

        for record in records:
            snapshot = record.get("snapshot") or {}
            score = snapshot.get("overall_institutional_score")

            try:
                scores.append(float(score))
            except (TypeError, ValueError):
                continue

        latest_score = scores[-1] if scores else None
        first_score = scores[0] if scores else None

        return {
            "symbol": symbol,
            "record_count": len(records),
            "scored_record_count": len(scores),
            "latest_score": latest_score,
            "first_score": first_score,
            "score_change": (
                round(latest_score - first_score, 2)
                if latest_score is not None and first_score is not None
                else None
            ),
            "average_score": (
                round(sum(scores) / len(scores), 2)
                if scores
                else None
            ),
            "status": "INSTITUTIONAL_MEMORY_SUMMARY_READY",
        }
