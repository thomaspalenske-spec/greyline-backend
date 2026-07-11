from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.institutional.institutional_feature_vector_engine import (
    InstitutionalFeatureVectorEngine,
)
from app.services.institutional.institutional_signal_history_engine import (
    InstitutionalSignalHistoryEngine,
)


class InstitutionalTrainingDatasetEngine:
    """
    Converts stored institutional snapshots into ordered feature rows.

    Safety:
    - Observation only.
    - No scoring influence.
    - No execution influence.
    - No model training or automatic promotion.
    """

    DATA_DIR = Path(
        "app/data/runtime/institutional_training_datasets"
    )
    SCHEMA_VERSION = 1

    def __init__(self):
        self.history_engine = (
            InstitutionalSignalHistoryEngine()
        )
        self.feature_engine = (
            InstitutionalFeatureVectorEngine()
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
    def _timestamp_value(
        snapshot: Dict[str, Any],
        vector: Dict[str, Any],
    ) -> Optional[str]:
        return (
            snapshot.get("timestamp")
            or vector.get("timestamp")
        )

    def build(
        self,
        symbol: str,
        limit: int = 500,
        provider: Optional[str] = None,
        require_collected: bool = False,
        include_source_path: bool = False,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        history = self.history_engine.history(
            symbol,
            limit=limit,
            provider=provider,
            require_collected=require_collected,
        )

        snapshots = (
            history.get("records")
            or []
        )

        rows: List[Dict[str, Any]] = []
        failed_vector_count = 0

        for snapshot in snapshots:
            try:
                vector = self.feature_engine.build(
                    snapshot
                )
            except Exception:
                failed_vector_count += 1
                continue

            row = dict(vector)

            row["observation_timestamp"] = (
                self._timestamp_value(
                    snapshot,
                    vector,
                )
            )

            row["snapshot_hash"] = (
                snapshot.get(
                    "snapshot_hash"
                )
            )

            row["source_schema_version"] = (
                snapshot.get(
                    "schema_version"
                )
            )

            row["dataset_schema_version"] = (
                self.SCHEMA_VERSION
            )

            if include_source_path:
                row["source_snapshot_path"] = (
                    snapshot.get(
                        "_snapshot_path"
                    )
                )

            row["execution_impact"] = (
                "OBSERVATION_ONLY"
            )

            rows.append(row)

        rows.sort(
            key=lambda row: (
                row.get(
                    "observation_timestamp"
                )
                or ""
            )
        )

        duplicate_hash_count = 0
        seen_hashes = set()
        deduplicated_rows = []

        for row in rows:
            snapshot_hash = row.get(
                "snapshot_hash"
            )

            if (
                snapshot_hash
                and snapshot_hash in seen_hashes
            ):
                duplicate_hash_count += 1
                continue

            if snapshot_hash:
                seen_hashes.add(
                    snapshot_hash
                )

            deduplicated_rows.append(
                row
            )

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "engine": (
                "InstitutionalTrainingDatasetEngine"
            ),
            "symbol": symbol,
            "provider_filter": provider,
            "require_collected": bool(
                require_collected
            ),
            "source_snapshot_count": len(
                snapshots
            ),
            "feature_row_count": len(
                deduplicated_rows
            ),
            "failed_vector_count": (
                failed_vector_count
            ),
            "duplicate_hash_count": (
                duplicate_hash_count
            ),
            "rows": deduplicated_rows,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_TRAINING_"
                "DATASET_READY"
                if deduplicated_rows
                else
                "INSTITUTIONAL_TRAINING_"
                "DATASET_EMPTY"
            ),
        }

    def persist(
        self,
        symbol: str,
        limit: int = 500,
        provider: Optional[str] = None,
        require_collected: bool = False,
    ) -> Dict[str, Any]:
        dataset = self.build(
            symbol,
            limit=limit,
            provider=provider,
            require_collected=require_collected,
            include_source_path=False,
        )

        rows = (
            dataset.get("rows")
            or []
        )

        symbol = dataset.get(
            "symbol"
        )

        destination = (
            self.DATA_DIR
            / f"{symbol}.jsonl"
        )

        with destination.open(
            "w",
            encoding="utf-8",
        ) as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        row,
                        separators=(",", ":"),
                        default=str,
                    )
                    + "\n"
                )

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "symbol": symbol,
            "dataset_path": str(
                destination
            ),
            "feature_row_count": len(
                rows
            ),
            "source_snapshot_count": (
                dataset.get(
                    "source_snapshot_count"
                )
            ),
            "failed_vector_count": (
                dataset.get(
                    "failed_vector_count"
                )
            ),
            "duplicate_hash_count": (
                dataset.get(
                    "duplicate_hash_count"
                )
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_TRAINING_"
                "DATASET_PERSISTED"
            ),
        }
