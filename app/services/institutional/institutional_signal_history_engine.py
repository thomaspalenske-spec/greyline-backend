from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class InstitutionalSignalHistoryEngine:
    """
    Reads institutional signal snapshots in chronological order.

    Observation only:
    - no scoring
    - no execution influence
    - no model changes
    """

    DATA_DIR = Path(
        "app/data/runtime/institutional_signal_snapshots"
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

    def _files(
        self,
        symbol: str,
    ) -> List[Path]:
        symbol_dir = (
            self.DATA_DIR
            / symbol
        )

        if not symbol_dir.exists():
            return []

        return sorted(
            path
            for path in symbol_dir.glob(
                "*/*.json"
            )
            if path.is_file()
        )

    @staticmethod
    def _read(
        path: Path,
    ) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(
                path.read_text()
            )
        except Exception:
            return None

        if not isinstance(
            value,
            dict,
        ):
            return None

        value = dict(value)
        value["_snapshot_path"] = str(
            path
        )

        return value

    def history(
        self,
        symbol: str,
        limit: int = 100,
        provider: Optional[str] = None,
        require_collected: bool = False,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        provider = (
            str(provider or "")
            .upper()
            .strip()
            or None
        )

        files = self._files(
            symbol
        )

        records = []
        unreadable_count = 0

        for path in files:
            snapshot = self._read(
                path
            )

            if snapshot is None:
                unreadable_count += 1
                continue

            providers = (
                snapshot.get(
                    "providers"
                )
                or {}
            )

            if provider:
                provider_result = (
                    providers.get(
                        provider
                    )
                )

                if not isinstance(
                    provider_result,
                    dict,
                ):
                    continue

                if (
                    require_collected
                    and provider_result.get(
                        "requested"
                    )
                    is not True
                ):
                    continue

            records.append(
                snapshot
            )

        records.sort(
            key=lambda row: (
                row.get("timestamp")
                or ""
            )
        )

        limit = max(
            1,
            int(limit),
        )

        records = records[
            -limit:
        ]

        now = datetime.now(
            timezone.utc
        )

        latest_timestamp = None
        oldest_timestamp = None

        if records:
            oldest_timestamp = (
                self._parse_timestamp(
                    records[0].get(
                        "timestamp"
                    )
                )
            )

            latest_timestamp = (
                self._parse_timestamp(
                    records[-1].get(
                        "timestamp"
                    )
                )
            )

        latest_age_seconds = (
            round(
                (
                    now
                    - latest_timestamp
                ).total_seconds(),
                2,
            )
            if latest_timestamp
            else None
        )

        provider_counts = {}

        for record in records:
            providers = (
                record.get("providers")
                or {}
            )

            for name, result in providers.items():
                stats = provider_counts.setdefault(
                    name,
                    {
                        "snapshot_count": 0,
                        "requested_count": 0,
                        "connected_count": 0,
                        "degraded_count": 0,
                    },
                )

                stats[
                    "snapshot_count"
                ] += 1

                if (
                    isinstance(result, dict)
                    and result.get(
                        "requested"
                    )
                    is True
                ):
                    stats[
                        "requested_count"
                    ] += 1

                if (
                    isinstance(result, dict)
                    and result.get(
                        "requested"
                    )
                    is True
                    and result.get(
                        "connected"
                    )
                    is True
                ):
                    stats[
                        "connected_count"
                    ] += 1

                if (
                    isinstance(result, dict)
                    and "DEGRADED"
                    in str(
                        result.get(
                            "status"
                        )
                        or ""
                    )
                ):
                    stats[
                        "degraded_count"
                    ] += 1

        for stats in provider_counts.values():
            requested = stats[
                "requested_count"
            ]

            connected = stats[
                "connected_count"
            ]

            stats[
                "connection_rate_pct"
            ] = (
                round(
                    connected
                    / requested
                    * 100.0,
                    2,
                )
                if requested
                else None
            )

        stale = bool(
            latest_age_seconds is None
            or latest_age_seconds
            > 3600
        )

        return {
            "timestamp": now.isoformat(),
            "symbol": symbol,
            "provider_filter": provider,
            "require_collected": bool(
                require_collected
            ),
            "file_count": len(files),
            "record_count": len(
                records
            ),
            "unreadable_file_count": (
                unreadable_count
            ),
            "oldest_snapshot_timestamp": (
                oldest_timestamp.isoformat()
                if oldest_timestamp
                else None
            ),
            "latest_snapshot_timestamp": (
                latest_timestamp.isoformat()
                if latest_timestamp
                else None
            ),
            "latest_snapshot_age_seconds": (
                latest_age_seconds
            ),
            "stale": stale,
            "provider_continuity": (
                provider_counts
            ),
            "records": records,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "HISTORY_READY"
                if records
                else
                "INSTITUTIONAL_SIGNAL_"
                "HISTORY_EMPTY"
            ),
        }

    def latest(
        self,
        symbol: str,
        provider: Optional[str] = None,
        require_collected: bool = False,
    ) -> Dict[str, Any]:
        result = self.history(
            symbol,
            limit=1,
            provider=provider,
            require_collected=(
                require_collected
            ),
        )

        records = (
            result.get("records")
            or []
        )

        return {
            "timestamp": result.get(
                "timestamp"
            ),
            "symbol": result.get(
                "symbol"
            ),
            "provider_filter": provider,
            "snapshot": (
                records[-1]
                if records
                else None
            ),
            "snapshot_found": bool(
                records
            ),
            "latest_snapshot_age_seconds": (
                result.get(
                    "latest_snapshot_age_seconds"
                )
            ),
            "stale": result.get(
                "stale"
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "LATEST_READY"
                if records
                else
                "INSTITUTIONAL_SIGNAL_"
                "LATEST_UNAVAILABLE"
            ),
        }
