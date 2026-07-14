import hashlib
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
        minimum_interval_seconds: int = 60,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be a dictionary")

        now = datetime.now(timezone.utc)
        path = self._path(symbol)

        # Accumulate a price point on EVERY cycle we were handed a fresh price, even if
        # the flow snapshot itself is about to be deduped/interval-skipped below. Flow
        # signals are often constant (so snapshots rarely change), but the fixed-horizon
        # join needs a dense price series — a price near both T and T+horizon. Decoupling
        # price recording from snapshot novelty is what makes the join actually succeed.
        if price is not None:
            try:
                self._co_record_price(symbol, now.isoformat(), price)
            except Exception:
                pass

        normalized_snapshot = dict(snapshot)
        normalized_snapshot.pop("timestamp", None)

        snapshot_json = json.dumps(
            normalized_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        snapshot_hash = hashlib.sha256(
            snapshot_json.encode("utf-8")
        ).hexdigest()

        latest = self.latest(symbol)

        if isinstance(latest, dict):
            latest_hash = latest.get("snapshot_hash")
            latest_timestamp = latest.get("timestamp")

            elapsed_seconds = None

            try:
                parsed = datetime.fromisoformat(
                    str(latest_timestamp).replace("Z", "+00:00")
                )
                elapsed_seconds = (now - parsed).total_seconds()
            except (TypeError, ValueError):
                pass

            if latest_hash == snapshot_hash:
                return {
                    "recorded": False,
                    "symbol": symbol,
                    "reason": "IDENTICAL_SNAPSHOT",
                    "path": str(path),
                    "status": "INSTITUTIONAL_MEMORY_DUPLICATE_SKIPPED",
                }

            if (
                elapsed_seconds is not None
                and elapsed_seconds < max(
                    0,
                    int(minimum_interval_seconds),
                )
            ):
                return {
                    "recorded": False,
                    "symbol": symbol,
                    "reason": "MINIMUM_INTERVAL_NOT_REACHED",
                    "elapsed_seconds": round(elapsed_seconds, 2),
                    "minimum_interval_seconds": int(
                        minimum_interval_seconds
                    ),
                    "path": str(path),
                    "status": "INSTITUTIONAL_MEMORY_INTERVAL_SKIPPED",
                }

        record = {
            "timestamp": now.isoformat(),
            "symbol": symbol,
            "source": source,
            "snapshot_hash": snapshot_hash,
            "snapshot": snapshot,
        }

        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, separators=(",", ":")) + "\n"
            )

        # Co-record the symbol's price at the SAME timestamp so every flow snapshot
        # has a joinable price for fixed-horizon / flow-skill validation. Never let a
        # price failure affect snapshot recording (the snapshot is already written).
        # When an explicit price was provided it was already recorded above (before the
        # dedup/interval gates); only fall back to a live quote fetch when none was given.
        if price is None:
            try:
                self._co_record_price(symbol, now.isoformat(), None)
            except Exception:
                pass

        return {
            "recorded": True,
            "symbol": symbol,
            "snapshot_hash": snapshot_hash,
            "path": str(path),
            "status": "INSTITUTIONAL_MEMORY_RECORDED",
        }

    @staticmethod
    def _co_record_price(symbol, timestamp, price=None):
        try:
            from app.services.price_history_store import PriceHistoryStore
            if price is None:
                from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
                q = TradeStationQuoteLiveEngine().get_quote(symbol)
                quotes = (q.get("response_json") or {}).get("Quotes") or []
                price = float((quotes[0] if quotes else {}).get("Last") or 0)
            if price and float(price) > 0:
                PriceHistoryStore().record(symbol, price, timestamp)
        except Exception:
            pass

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
