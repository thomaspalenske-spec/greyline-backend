from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, Optional

from app.services.institutional.institutional_signal_collection_engine import (
    InstitutionalSignalCollectionEngine,
)
from app.services.tradestation_quote_live_engine import (
    TradeStationQuoteLiveEngine,
)


class InstitutionalSignalSnapshotEngine:
    """
    Persists observation-only institutional signal snapshots.

    Safety:
    - No scoring changes.
    - No execution influence.
    - Provider failures remain isolated by the collection engine.
    - Duplicate snapshots can be suppressed.
    """

    DATA_DIR = Path(
        "app/data/runtime/institutional_signal_snapshots"
    )
    SCHEMA_VERSION = 1

    def __init__(self):
        self.collector = (
            InstitutionalSignalCollectionEngine()
        )
        self.quote_engine = (
            TradeStationQuoteLiveEngine()
        )

        self.DATA_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _symbol(symbol: str) -> str:
        value = (
            symbol
            or ""
        ).upper().strip()

        if not value:
            raise ValueError(
                "symbol is required"
            )

        return value

    @staticmethod
    def _stable_hash(
        payload: Dict[str, Any],
    ) -> str:
        normalized = dict(payload)

        normalized.pop(
            "timestamp",
            None,
        )
        normalized.pop(
            "collection_latency_seconds",
            None,
        )

        encoded = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")

        return hashlib.sha256(
            encoded
        ).hexdigest()

    def _symbol_dir(
        self,
        symbol: str,
        timestamp: datetime,
    ) -> Path:
        path = (
            self.DATA_DIR
            / symbol
            / timestamp.strftime("%Y-%m-%d")
        )

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    def _latest_snapshot(
        self,
        symbol: str,
    ) -> Optional[Dict[str, Any]]:
        symbol_dir = (
            self.DATA_DIR
            / symbol
        )

        if not symbol_dir.exists():
            return None

        files = sorted(
            symbol_dir.glob(
                "*/*.json"
            )
        )

        if not files:
            return None

        try:
            value = json.loads(
                files[-1].read_text()
            )
        except Exception:
            return None

        return (
            value
            if isinstance(value, dict)
            else None
        )

    @staticmethod
    def _float(
        value,
    ):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None

        return (
            parsed
            if parsed > 0
            else None
        )

    def _underlying_price(
        self,
        symbol,
        collection,
    ):
        providers = (
            collection.get("providers")
            or {}
        )

        tradestation = (
            providers.get("TRADESTATION")
            or {}
        )

        signals = (
            tradestation.get("signals")
            or {}
        )

        quote = (
            signals.get("quote")
            or {}
        )

        fields = (
            quote.get("fields")
            or {}
        )

        collected_price = self._float(
            fields.get("Last")
            or fields.get("Close")
        )

        if collected_price is not None:
            return {
                "price": collected_price,
                "price_source": (
                    "TRADESTATION_COLLECTION_QUOTE"
                ),
                "trade_time": fields.get(
                    "TradeTime"
                ),
                "quote_status": quote.get(
                    "source_status"
                ),
            }

        try:
            result = self.quote_engine.get_quote(
                symbol
            )
        except Exception as exc:
            return {
                "price": None,
                "price_source": None,
                "trade_time": None,
                "quote_status": (
                    "TRADESTATION_SNAPSHOT_QUOTE_"
                    "DEGRADED"
                ),
                "error": repr(exc),
            }

        quotes = (
            (result.get("response_json") or {})
            .get("Quotes")
            or []
        )

        row = (
            quotes[0]
            if quotes
            and isinstance(quotes[0], dict)
            else {}
        )

        return {
            "price": self._float(
                row.get("Last")
                or row.get("Close")
            ),
            "price_source": (
                "TRADESTATION_SNAPSHOT_QUOTE"
            ),
            "trade_time": row.get(
                "TradeTime"
            ),
            "quote_status": result.get(
                "status"
            ),
            "cache_hit": result.get(
                "cache_hit"
            ),
            "cache_age_seconds": result.get(
                "cache_age_seconds"
            ),
        }

    def capture(
        self,
        symbol: str,
        collect_unusual_whales: bool = False,
        unusual_whales_signals: Optional[
            Iterable[str]
        ] = None,
        collect_tradestation: bool = False,
        include_tradestation_option_chain: bool = False,
        tradestation_expiration: Optional[
            str
        ] = None,
        tradestation_option_type: str = "All",
        tradestation_max_contracts: int = 10,
        force_refresh: bool = False,
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        started_at = perf_counter()
        captured_at = datetime.now(
            timezone.utc
        )

        collection = self.collector.collect(
            symbol,
            collect_unusual_whales=(
                collect_unusual_whales
            ),
            unusual_whales_signals=(
                unusual_whales_signals
            ),
            collect_tradestation=(
                collect_tradestation
            ),
            include_tradestation_option_chain=(
                include_tradestation_option_chain
            ),
            tradestation_expiration=(
                tradestation_expiration
            ),
            tradestation_option_type=(
                tradestation_option_type
            ),
            tradestation_max_contracts=(
                tradestation_max_contracts
            ),
            force_refresh=force_refresh,
        )

        underlying = self._underlying_price(
            symbol,
            collection,
        )

        latency_seconds = round(
            perf_counter() - started_at,
            4,
        )

        snapshot = {
            "timestamp": (
                captured_at.isoformat()
            ),
            "schema_version": (
                self.SCHEMA_VERSION
            ),
            "engine": (
                "InstitutionalSignalSnapshotEngine"
            ),
            "symbol": symbol,
            "snapshot_price": underlying.get(
                "price"
            ),
            "snapshot_price_source": (
                underlying.get(
                    "price_source"
                )
            ),
            "snapshot_price_trade_time": (
                underlying.get(
                    "trade_time"
                )
            ),
            "snapshot_price_quote_status": (
                underlying.get(
                    "quote_status"
                )
            ),
            "collection_latency_seconds": (
                latency_seconds
            ),
            "provider_health": collection.get(
                "provider_health"
            ),
            "requested_provider_count": (
                collection.get(
                    "requested_provider_count"
                )
            ),
            "connected_provider_count": (
                collection.get(
                    "connected_provider_count"
                )
            ),
            "degraded_provider_count": (
                collection.get(
                    "degraded_provider_count"
                )
            ),
            "providers": (
                collection.get("providers")
                or {}
            ),
            "collection_status": (
                collection.get("status")
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "SNAPSHOT_READY"
            ),
        }

        snapshot_hash = self._stable_hash(
            snapshot
        )

        snapshot[
            "snapshot_hash"
        ] = snapshot_hash

        latest = self._latest_snapshot(
            symbol
        )

        if (
            deduplicate
            and isinstance(latest, dict)
            and latest.get(
                "snapshot_hash"
            )
            == snapshot_hash
        ):
            return {
                "timestamp": (
                    captured_at.isoformat()
                ),
                "symbol": symbol,
                "snapshot_recorded": False,
                "deduplicated": True,
                "snapshot_hash": (
                    snapshot_hash
                ),
                "collection_latency_seconds": (
                    latency_seconds
                ),
                "provider_health": (
                    snapshot.get(
                        "provider_health"
                    )
                ),
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "status": (
                    "INSTITUTIONAL_SIGNAL_"
                    "SNAPSHOT_DUPLICATE_SKIPPED"
                ),
            }

        destination = (
            self._symbol_dir(
                symbol,
                captured_at,
            )
            / (
                captured_at.strftime(
                    "%H-%M-%S-%f"
                )
                + ".json"
            )
        )

        destination.write_text(
            json.dumps(
                snapshot,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

        return {
            "timestamp": (
                captured_at.isoformat()
            ),
            "symbol": symbol,
            "snapshot_recorded": True,
            "deduplicated": False,
            "snapshot_hash": (
                snapshot_hash
            ),
            "snapshot_path": str(
                destination
            ),
            "collection_latency_seconds": (
                latency_seconds
            ),
            "provider_health": (
                snapshot.get(
                    "provider_health"
                )
            ),
            "snapshot_price": (
                snapshot.get(
                    "snapshot_price"
                )
            ),
            "snapshot_price_source": (
                snapshot.get(
                    "snapshot_price_source"
                )
            ),
            "requested_provider_count": (
                snapshot.get(
                    "requested_provider_count"
                )
            ),
            "connected_provider_count": (
                snapshot.get(
                    "connected_provider_count"
                )
            ),
            "degraded_provider_count": (
                snapshot.get(
                    "degraded_provider_count"
                )
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "SNAPSHOT_RECORDED"
            ),
        }
