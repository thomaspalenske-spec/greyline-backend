from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.institutional.institutional_feature_vector_engine import (
    InstitutionalFeatureVectorEngine,
)
from app.services.institutional.institutional_signal_history_engine import (
    InstitutionalSignalHistoryEngine,
)
from app.services.tradestation_quote_live_engine import (
    TradeStationQuoteLiveEngine,
)


class InstitutionalOutcomeLabelingEngine:
    """
    Pairs institutional observations with subsequent realized returns.

    Safety:
    - Observation only.
    - No scoring changes.
    - No execution influence.
    - No look-ahead during snapshot creation.
    - Supplied prices can be used for deterministic tests.
    """

    SCHEMA_VERSION = 1

    def __init__(self):
        self.history = (
            InstitutionalSignalHistoryEngine()
        )
        self.features = (
            InstitutionalFeatureVectorEngine()
        )
        self.quote_engine = (
            TradeStationQuoteLiveEngine()
        )

    @staticmethod
    def _float(
        value: Any,
    ) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None

        return parsed if parsed > 0 else None

    @staticmethod
    def _parse_timestamp(
        value: Any,
    ) -> Optional[datetime]:
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except Exception:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    def _snapshot_price(
        self,
        snapshot: Dict[str, Any],
    ) -> Optional[float]:
        direct_price = self._float(
            snapshot.get(
                "snapshot_price"
            )
        )

        if direct_price is not None:
            return direct_price

        providers = (
            snapshot.get("providers")
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

        return self._float(
            fields.get("Last")
            or fields.get("Close")
        )

    def _current_price(
        self,
        symbol: str,
        supplied_price=None,
    ) -> Dict[str, Any]:
        supplied = self._float(
            supplied_price
        )

        if supplied is not None:
            return {
                "price": supplied,
                "price_source": (
                    "SUPPLIED_MARKET_PRICE"
                ),
                "quote_status": None,
                "trade_time": None,
            }

        result = self.quote_engine.get_quote(
            symbol
        )

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
            ),
            "price_source": (
                "TRADESTATION_LIVE_QUOTE"
            ),
            "quote_status": result.get(
                "status"
            ),
            "trade_time": row.get(
                "TradeTime"
            ),
        }

    @staticmethod
    def _direction(
        return_pct: float,
        neutral_tolerance_pct: float,
    ) -> str:
        if return_pct > neutral_tolerance_pct:
            return "UP"

        if return_pct < -neutral_tolerance_pct:
            return "DOWN"

        return "FLAT"

    def label(
        self,
        symbol: str,
        limit: int = 500,
        min_age_minutes: int = 60,
        market_price=None,
        neutral_tolerance_pct: float = 0.25,
    ) -> Dict[str, Any]:
        symbol = (
            symbol
            or ""
        ).upper().strip()

        if not symbol:
            raise ValueError(
                "symbol is required"
            )

        history = self.history.history(
            symbol,
            limit=limit,
        )

        snapshots = (
            history.get("records")
            or []
        )

        current = self._current_price(
            symbol,
            supplied_price=market_price,
        )

        current_price = current.get(
            "price"
        )

        now = datetime.now(
            timezone.utc
        )

        rows: List[Dict[str, Any]] = []
        labeled_count = 0
        pending_count = 0
        missing_snapshot_price_count = 0

        for snapshot in snapshots:
            feature_vector = (
                self.features.build(
                    snapshot
                )
            )

            observation_time = (
                self._parse_timestamp(
                    snapshot.get(
                        "timestamp"
                    )
                )
            )

            age_minutes = (
                round(
                    (
                        now
                        - observation_time
                    ).total_seconds()
                    / 60.0,
                    2,
                )
                if observation_time
                else None
            )

            snapshot_price = (
                self._snapshot_price(
                    snapshot
                )
            )

            eligible = bool(
                age_minutes is not None
                and age_minutes
                >= min_age_minutes
            )

            return_pct = None
            realized_direction = None
            label_status = (
                "INSTITUTIONAL_OUTCOME_PENDING"
            )

            if snapshot_price is None:
                missing_snapshot_price_count += 1
                label_status = (
                    "INSTITUTIONAL_OUTCOME_"
                    "SNAPSHOT_PRICE_UNAVAILABLE"
                )

            elif not eligible:
                pending_count += 1
                label_status = (
                    "INSTITUTIONAL_OUTCOME_"
                    "PENDING_MATURITY"
                )

            elif current_price is None:
                pending_count += 1
                label_status = (
                    "INSTITUTIONAL_OUTCOME_"
                    "CURRENT_PRICE_UNAVAILABLE"
                )

            else:
                return_pct = round(
                    (
                        (
                            current_price
                            - snapshot_price
                        )
                        / snapshot_price
                    )
                    * 100.0,
                    4,
                )

                realized_direction = (
                    self._direction(
                        return_pct,
                        neutral_tolerance_pct,
                    )
                )

                labeled_count += 1

                label_status = (
                    "INSTITUTIONAL_OUTCOME_LABELED"
                )

            rows.append({
                **feature_vector,
                "observation_timestamp": (
                    snapshot.get(
                        "timestamp"
                    )
                ),
                "snapshot_hash": (
                    snapshot.get(
                        "snapshot_hash"
                    )
                ),
                "snapshot_price": (
                    snapshot_price
                ),
                "current_price": (
                    current_price
                ),
                "price_source": (
                    current.get(
                        "price_source"
                    )
                ),
                "quote_status": (
                    current.get(
                        "quote_status"
                    )
                ),
                "quote_trade_time": (
                    current.get(
                        "trade_time"
                    )
                ),
                "observation_age_minutes": (
                    age_minutes
                ),
                "minimum_age_minutes": (
                    min_age_minutes
                ),
                "eligible_for_labeling": (
                    eligible
                ),
                "realized_return_pct": (
                    return_pct
                ),
                "realized_direction": (
                    realized_direction
                ),
                "label_status": (
                    label_status
                ),
                "label_schema_version": (
                    self.SCHEMA_VERSION
                ),
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
            })

        return {
            "timestamp": now.isoformat(),
            "engine": (
                "InstitutionalOutcomeLabelingEngine"
            ),
            "symbol": symbol,
            "source_snapshot_count": len(
                snapshots
            ),
            "row_count": len(rows),
            "labeled_count": labeled_count,
            "pending_count": pending_count,
            "missing_snapshot_price_count": (
                missing_snapshot_price_count
            ),
            "current_price": current_price,
            "price_source": current.get(
                "price_source"
            ),
            "rows": rows,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_OUTCOME_"
                "LABELING_READY"
            ),
        }
