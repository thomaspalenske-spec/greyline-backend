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

    # Where the rotation cursor lives, so coverage continues across restarts.
    CURSOR_PATH = Path(
        "app/data/institutional_memory_sweep_cursor.json"
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

    def _read_cursor(self):
        try:
            import json
            return int(
                json.loads(
                    self.CURSOR_PATH.read_text()
                ).get("cursor", 0)
            )
        except Exception:
            return 0

    def _write_cursor(self, cursor, universe_size):
        try:
            import json
            self.CURSOR_PATH.parent.mkdir(
                parents=True, exist_ok=True
            )
            self.CURSOR_PATH.write_text(
                json.dumps({
                    "cursor": int(cursor),
                    "universe_size": int(
                        universe_size
                    ),
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                })
            )
        except Exception:
            pass   # a cursor write failure must never break an observation sweep

    def _rotate(self, symbols, limit):
        """The next `limit` symbols round-robin, so every symbol is eventually collected.

        Returns (selected, next_cursor). Wraps around the end of the list, so a limit
        larger than the universe simply returns the whole universe once.
        """
        if not symbols or limit <= 0:
            return [], 0
        total = len(symbols)
        if limit >= total:
            return list(symbols), 0
        start = self._read_cursor() % total
        picked = [
            symbols[(start + i) % total]
            for i in range(limit)
        ]
        return picked, (start + limit) % total

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

        # ROTATE, don't truncate. `selected` is sorted, so selected[:limit] always took the
        # alphabetically first `limit` symbols — everything after them was collected NEVER,
        # not merely less often. Worse, the window drifted: adding a symbol early in the
        # alphabet silently pushed a later one out of collection entirely. That is why SPY
        # had 1 distinct day and NVDA 4 while AAPL had 8, and it biased the flow dataset
        # the whole stage-2 verdict was computed from.
        #
        # Rotating a persisted cursor keeps the per-cycle cost identical (~31 uncached UW
        # requests per symbol) while giving every symbol coverage: with N symbols and a
        # limit of L, each is sampled every ceil(N/L) cycles instead of never.
        universe_size = len(selected)
        rotated, cursor = self._rotate(selected, limit)
        selected = rotated

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

        # Advance only after the sweep, so a crash mid-cycle re-covers the same slice
        # rather than skipping it.
        self._write_cursor(cursor, universe_size)

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "engine": (
                "InstitutionalSignalSnapshotSweepEngine"
            ),
            "symbol_source": symbol_source,
            "symbol_count": len(selected),
            "universe_size": universe_size,
            "rotation_cursor": cursor,
            # Cycles for every symbol to be sampled once. Coverage is now a latency, not
            # an exclusion — the number to watch when widening the universe.
            "cycles_for_full_coverage": (
                1 if limit >= universe_size or limit <= 0
                else -(-universe_size // limit)
            ),
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
