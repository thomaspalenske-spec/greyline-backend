from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.services.institutional.institutional_signal_snapshot_engine import (
    InstitutionalSignalSnapshotEngine,
)


class InstitutionalSignalSnapshotSweepEngine:
    """
    Captures institutional observation snapshots across the known
    institutional-memory universe.

    Safety:
    - Observation only.
    - Bounded symbol count.
    - Unusual Whales collection remains opt-in.
    - TradeStation option-chain collection remains opt-in.
    - Individual symbol failures do not stop the sweep.
    """

    MEMORY_DIR = Path(
        "app/data/institutional_memory"
    )

    DEFAULT_LIMIT = 10
    MAXIMUM_LIMIT = 50

    def __init__(self):
        self.snapshot_engine = (
            InstitutionalSignalSnapshotEngine()
        )

    @staticmethod
    def _normalize_symbols(
        symbols: Optional[Iterable[str]],
    ):
        if symbols is None:
            return None

        return sorted({
            str(symbol or "")
            .upper()
            .strip()
            for symbol in symbols
            if str(symbol or "").strip()
        })

    def _discovered_symbols(self):
        if not self.MEMORY_DIR.exists():
            return []

        return sorted({
            path.stem.upper()
            for path in self.MEMORY_DIR.glob(
                "*.jsonl"
            )
            if path.is_file()
        })

    def run(
        self,
        symbols: Optional[Iterable[str]] = None,
        limit: int = DEFAULT_LIMIT,
        collect_unusual_whales: bool = False,
        unusual_whales_signals=None,
        collect_tradestation: bool = False,
        include_tradestation_option_chain: bool = False,
        tradestation_expiration=None,
        tradestation_option_type: str = "All",
        tradestation_max_contracts: int = 5,
        force_refresh: bool = False,
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        selected = self._normalize_symbols(
            symbols
        )

        symbol_source = "SUPPLIED_SYMBOLS"

        if selected is None:
            selected = self._discovered_symbols()
            symbol_source = (
                "INSTITUTIONAL_MEMORY_DISCOVERY"
            )

        limit = max(
            0,
            min(
                int(limit),
                self.MAXIMUM_LIMIT,
            ),
        )

        selected = selected[:limit]

        results = []
        recorded_symbols = []
        deduplicated_symbols = []
        degraded_symbols = []

        for symbol in selected:
            try:
                result = (
                    self.snapshot_engine.capture(
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
                        deduplicate=deduplicate,
                    )
                )
            except Exception as exc:
                result = {
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "symbol": symbol,
                    "snapshot_recorded": False,
                    "deduplicated": False,
                    "error": repr(exc),
                    "execution_impact": (
                        "OBSERVATION_ONLY"
                    ),
                    "status": (
                        "INSTITUTIONAL_SIGNAL_"
                        "SNAPSHOT_DEGRADED"
                    ),
                }

            results.append(result)

            if result.get(
                "snapshot_recorded"
            ) is True:
                recorded_symbols.append(
                    symbol
                )

            if result.get(
                "deduplicated"
            ) is True:
                deduplicated_symbols.append(
                    symbol
                )

            if "DEGRADED" in str(
                result.get("status") or ""
            ):
                degraded_symbols.append(
                    symbol
                )

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "engine": (
                "InstitutionalSignalSnapshotSweepEngine"
            ),
            "symbol_source": symbol_source,
            "symbol_count": len(selected),
            "symbols": selected,
            "snapshot_recorded_count": len(
                recorded_symbols
            ),
            "recorded_symbols": (
                recorded_symbols
            ),
            "deduplicated_count": len(
                deduplicated_symbols
            ),
            "deduplicated_symbols": (
                deduplicated_symbols
            ),
            "degraded_count": len(
                degraded_symbols
            ),
            "degraded_symbols": (
                degraded_symbols
            ),
            "collect_unusual_whales": bool(
                collect_unusual_whales
            ),
            "collect_tradestation": bool(
                collect_tradestation
            ),
            "include_tradestation_option_chain": bool(
                include_tradestation_option_chain
            ),
            "results": results,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "SNAPSHOT_SWEEP_READY"
            ),
        }
