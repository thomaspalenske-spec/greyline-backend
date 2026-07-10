from statistics import mean
from typing import Any, Dict, List

from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)


class InstitutionalValidationEngine:
    SIGNALS = [
        "institutional_buying_score",
        "institutional_selling_score",
        "dark_pool_score",
        "dealer_gamma_score",
        "open_interest_score",
        "strike_concentration_score",
        "expiry_alignment_score",
        "variance_risk_score",
        "greek_flow_score",
        "spot_gamma_score",
        "lit_flow_score",
        "market_tide_score",
        "sector_tide_score",
        "ownership_score",
        "short_interest_score",
        "insider_score",
        "congress_score",
        "overall_institutional_score",
    ]

    def __init__(self):
        self.memory = InstitutionalMemoryEngine()

    @staticmethod
    def _float(value: Any):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def evaluate(
        self,
        symbol: str,
        limit: int = 500,
    ) -> Dict[str, Any]:
        symbol = (symbol or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        records = self.memory.history(symbol, limit=limit)
        snapshots: List[Dict[str, Any]] = [
            record.get("snapshot") or {}
            for record in records
            if isinstance(record, dict)
        ]

        signal_statistics = {}

        for signal in self.SIGNALS:
            values = []

            for snapshot in snapshots:
                value = self._float(snapshot.get(signal))

                if value is not None:
                    values.append(value)

            signal_statistics[signal] = {
                "sample_count": len(values),
                "latest": values[-1] if values else None,
                "minimum": round(min(values), 2) if values else None,
                "maximum": round(max(values), 2) if values else None,
                "average": round(mean(values), 2) if values else None,
                "change": (
                    round(values[-1] - values[0], 2)
                    if len(values) >= 2
                    else 0.0 if len(values) == 1
                    else None
                ),
            }

        overall_values = [
            self._float(snapshot.get("overall_institutional_score"))
            for snapshot in snapshots
        ]
        overall_values = [
            value for value in overall_values
            if value is not None
        ]

        if len(overall_values) >= 3:
            recent_window = overall_values[-3:]
            institutional_trend = (
                "IMPROVING"
                if recent_window[-1] > recent_window[0]
                else "DETERIORATING"
                if recent_window[-1] < recent_window[0]
                else "STABLE"
            )
        else:
            institutional_trend = "INSUFFICIENT_HISTORY"

        validated = len(overall_values) >= 20

        return {
            "symbol": symbol,
            "record_count": len(records),
            "scored_record_count": len(overall_values),
            "validated": validated,
            "minimum_validation_records": 20,
            "institutional_trend": institutional_trend,
            "signal_statistics": signal_statistics,
            "status": (
                "INSTITUTIONAL_VALIDATION_READY"
                if validated
                else "INSTITUTIONAL_VALIDATION_COLLECTING_DATA"
            ),
        }
