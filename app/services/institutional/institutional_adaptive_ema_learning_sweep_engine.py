from datetime import datetime
from pathlib import Path

from app.services.institutional.institutional_adaptive_ema_learning_engine import (
    InstitutionalAdaptiveEmaLearningEngine,
)


class InstitutionalAdaptiveEmaLearningSweepEngine:
    """
    Runs adaptive EMA learning across symbols that already have
    institutional-memory history.

    This is forecast-model learning only. It does not grant execution
    permission or bypass predictive-validation gates.
    """

    MEMORY_DIR = Path(
        "app/data/institutional_memory"
    )

    def _symbols(self):
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
        limit=None,
        persist=True,
    ):
        symbols = self._symbols()

        if limit is not None:
            symbols = symbols[
                :max(0, int(limit))
            ]

        learner = (
            InstitutionalAdaptiveEmaLearningEngine()
        )

        results = []
        updated_symbols = []
        collecting_symbols = []
        degraded_symbols = []

        for symbol in symbols:
            try:
                result = learner.evaluate(
                    symbol,
                    persist=persist,
                )
            except Exception as exc:
                result = {
                    "symbol": symbol,
                    "profile_updated": False,
                    "error": repr(exc),
                    "execution_impact": (
                        "OBSERVATION_ONLY"
                    ),
                    "status": (
                        "INSTITUTIONAL_ADAPTIVE_EMA_"
                        "LEARNING_DEGRADED"
                    ),
                }

            results.append(result)

            if result.get(
                "profile_updated"
            ) is True:
                updated_symbols.append(symbol)

            status = str(
                result.get("status") or ""
            )

            if status.endswith(
                "COLLECTING_DATA"
            ):
                collecting_symbols.append(
                    symbol
                )

            if status.endswith(
                "DEGRADED"
            ):
                degraded_symbols.append(
                    symbol
                )

        return {
            "timestamp": (
                datetime.utcnow().isoformat()
            ),
            "symbol_count": len(symbols),
            "symbols": symbols,
            "symbols_evaluated": len(
                results
            ),
            "profile_update_count": len(
                updated_symbols
            ),
            "updated_symbols": (
                updated_symbols
            ),
            "collecting_symbol_count": len(
                collecting_symbols
            ),
            "collecting_symbols": (
                collecting_symbols
            ),
            "degraded_symbol_count": len(
                degraded_symbols
            ),
            "degraded_symbols": (
                degraded_symbols
            ),
            "persist": bool(persist),
            "results": results,
            "execution_impact": (
                "FORECAST_MODEL_ONLY"
                if updated_symbols
                else "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_ADAPTIVE_EMA_"
                "LEARNING_SWEEP_READY"
            ),
        }
