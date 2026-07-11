from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.services.institutional.institutional_inference_engine import (
    InstitutionalInferenceEngine,
)
from app.services.institutional.institutional_outcome_labeling_engine import (
    InstitutionalOutcomeLabelingEngine,
)
from app.services.institutional.institutional_pattern_learning_engine import (
    InstitutionalPatternLearningEngine,
)
from app.services.institutional.institutional_signal_history_engine import (
    InstitutionalSignalHistoryEngine,
)


class InstitutionalRetrainingOrchestratorEngine:
    """
    Rebuilds institutional learning artifacts from stored snapshots.

    Safety:
    - Observation only.
    - No scoring or execution integration.
    - No provider collection calls.
    - Individual symbol failures are isolated.
    - Models remain non-actionable until inference confidence gates pass.
    """

    MEMORY_DIR = Path(
        "app/data/institutional_memory"
    )

    MODEL_DIR = Path(
        "app/data/runtime/institutional_models"
    )

    DEFAULT_LIMIT = 10
    MAXIMUM_LIMIT = 50
    SCHEMA_VERSION = 1

    def __init__(self):
        self.history = (
            InstitutionalSignalHistoryEngine()
        )
        self.labeler = (
            InstitutionalOutcomeLabelingEngine()
        )
        self.learner = (
            InstitutionalPatternLearningEngine()
        )
        self.inference = (
            InstitutionalInferenceEngine()
        )

        self.MODEL_DIR.mkdir(
            parents=True,
            exist_ok=True,
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
        symbols = set()

        if self.MEMORY_DIR.exists():
            symbols.update({
                path.stem.upper()
                for path in self.MEMORY_DIR.glob(
                    "*.jsonl"
                )
                if path.is_file()
            })

        snapshot_dir = (
            self.history.DATA_DIR
        )

        if snapshot_dir.exists():
            symbols.update({
                path.name.upper()
                for path in snapshot_dir.iterdir()
                if path.is_dir()
            })

        return sorted(symbols)

    def _model_path(
        self,
        symbol: str,
    ) -> Path:
        return (
            self.MODEL_DIR
            / f"{symbol}.json"
        )

    def _persist_model(
        self,
        symbol: str,
        model: Dict[str, Any],
    ) -> str:
        path = self._model_path(
            symbol
        )

        path.write_text(
            json.dumps(
                model,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

        return str(path)

    def retrain_symbol(
        self,
        symbol: str,
        min_age_minutes: int = 60,
        market_price=None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        symbol = (
            symbol
            or ""
        ).upper().strip()

        if not symbol:
            raise ValueError(
                "symbol is required"
            )

        labeled = self.labeler.label(
            symbol,
            min_age_minutes=min_age_minutes,
            market_price=market_price,
        )

        patterns = self.learner.train(
            labeled
        )

        latest_result = self.history.latest(
            symbol
        )

        snapshot = (
            latest_result.get("snapshot")
            or {}
        )

        if snapshot:
            inference = self.inference.infer(
                snapshot,
                patterns,
            )
        else:
            inference = {
                "symbol": symbol,
                "institutional_pattern_score": 50.0,
                "labeled_sample_count": (
                    patterns.get(
                        "sample_count"
                    )
                    or 0
                ),
                "actionable": False,
                "promotion_state": (
                    "NO_SNAPSHOT_AVAILABLE"
                ),
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "status": (
                    "INSTITUTIONAL_INFERENCE_"
                    "SNAPSHOT_UNAVAILABLE"
                ),
            }

        model = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "schema_version": (
                self.SCHEMA_VERSION
            ),
            "engine": (
                "InstitutionalRetrainingOrchestratorEngine"
            ),
            "symbol": symbol,
            "source_snapshot_count": (
                labeled.get(
                    "source_snapshot_count"
                )
                or 0
            ),
            "labeled_count": (
                labeled.get(
                    "labeled_count"
                )
                or 0
            ),
            "pending_count": (
                labeled.get(
                    "pending_count"
                )
                or 0
            ),
            "missing_snapshot_price_count": (
                labeled.get(
                    "missing_snapshot_price_count"
                )
                or 0
            ),
            "pattern_sample_count": (
                patterns.get(
                    "sample_count"
                )
                or 0
            ),
            "pattern_count": len(
                patterns.get(
                    "patterns"
                )
                or {}
            ),
            "patterns": (
                patterns.get(
                    "patterns"
                )
                or {}
            ),
            "institutional_pattern_score": (
                inference.get(
                    "institutional_pattern_score"
                )
            ),
            "raw_institutional_pattern_score": (
                inference.get(
                    "raw_institutional_pattern_score"
                )
            ),
            "labeled_sample_count": (
                inference.get(
                    "labeled_sample_count"
                )
            ),
            "minimum_labeled_samples": (
                inference.get(
                    "minimum_labeled_samples"
                )
            ),
            "sample_confidence_pct": (
                inference.get(
                    "sample_confidence_pct"
                )
            ),
            "confidence_state": (
                inference.get(
                    "confidence_state"
                )
            ),
            "actionable": (
                inference.get(
                    "actionable"
                )
                is True
            ),
            "promotion_state": (
                inference.get(
                    "promotion_state"
                )
            ),
            "inference_status": (
                inference.get(
                    "status"
                )
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_RETRAINING_"
                "MODEL_READY"
            ),
        }

        model_path = None

        if persist:
            model_path = self._persist_model(
                symbol,
                model,
            )

        return {
            **model,
            "model_persisted": bool(
                persist
            ),
            "model_path": model_path,
        }

    def run(
        self,
        symbols: Optional[
            Iterable[str]
        ] = None,
        limit: int = DEFAULT_LIMIT,
        min_age_minutes: int = 60,
        market_prices=None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        selected = self._normalize_symbols(
            symbols
        )

        symbol_source = "SUPPLIED_SYMBOLS"

        if selected is None:
            selected = (
                self._discovered_symbols()
            )
            symbol_source = (
                "INSTITUTIONAL_DATA_DISCOVERY"
            )

        limit = max(
            0,
            min(
                int(limit),
                self.MAXIMUM_LIMIT,
            ),
        )

        selected = selected[:limit]
        market_prices = (
            market_prices
            if isinstance(
                market_prices,
                dict,
            )
            else {}
        )

        results = []
        ready_symbols = []
        collecting_symbols = []
        actionable_symbols = []
        degraded_symbols = []

        for symbol in selected:
            try:
                result = self.retrain_symbol(
                    symbol,
                    min_age_minutes=(
                        min_age_minutes
                    ),
                    market_price=(
                        market_prices.get(
                            symbol
                        )
                    ),
                    persist=persist,
                )
            except Exception as exc:
                result = {
                    "timestamp": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "symbol": symbol,
                    "model_persisted": False,
                    "actionable": False,
                    "error": repr(exc),
                    "execution_impact": (
                        "OBSERVATION_ONLY"
                    ),
                    "status": (
                        "INSTITUTIONAL_RETRAINING_"
                        "DEGRADED"
                    ),
                }

            results.append(result)

            status = str(
                result.get("status")
                or ""
            )

            if status.endswith(
                "MODEL_READY"
            ):
                ready_symbols.append(
                    symbol
                )

            if (
                result.get("actionable")
                is True
            ):
                actionable_symbols.append(
                    symbol
                )
            else:
                collecting_symbols.append(
                    symbol
                )

            if "DEGRADED" in status:
                degraded_symbols.append(
                    symbol
                )

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "engine": (
                "InstitutionalRetrainingOrchestratorEngine"
            ),
            "symbol_source": symbol_source,
            "symbol_count": len(
                selected
            ),
            "symbols": selected,
            "model_ready_count": len(
                ready_symbols
            ),
            "ready_symbols": ready_symbols,
            "collecting_count": len(
                collecting_symbols
            ),
            "collecting_symbols": (
                collecting_symbols
            ),
            "actionable_count": len(
                actionable_symbols
            ),
            "actionable_symbols": (
                actionable_symbols
            ),
            "degraded_count": len(
                degraded_symbols
            ),
            "degraded_symbols": (
                degraded_symbols
            ),
            "persist": bool(
                persist
            ),
            "results": results,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_RETRAINING_"
                "ORCHESTRATOR_READY"
            ),
        }
