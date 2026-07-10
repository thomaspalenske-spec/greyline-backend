from typing import Any, Dict, List


class InstitutionalAttributionEngine:
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
    ]

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(
        self,
        trade_id: str,
        symbol: str,
        entry_snapshot: Dict[str, Any],
        exit_snapshot: Dict[str, Any],
        realized_pnl: float,
    ) -> Dict[str, Any]:
        if not isinstance(entry_snapshot, dict):
            raise TypeError("entry_snapshot must be a dictionary")

        if not isinstance(exit_snapshot, dict):
            raise TypeError("exit_snapshot must be a dictionary")

        changes: List[Dict[str, Any]] = []

        for signal in self.SIGNALS:
            entry_value = self._float(entry_snapshot.get(signal))
            exit_value = self._float(exit_snapshot.get(signal))
            change = round(exit_value - entry_value, 2)

            changes.append({
                "signal": signal,
                "entry": round(entry_value, 2),
                "exit": round(exit_value, 2),
                "change": change,
            })

        strongest_improvements = sorted(
            [
                row
                for row in changes
                if row["change"] > 0
            ],
            key=lambda row: row["change"],
            reverse=True,
        )[:5]

        strongest_deteriorations = sorted(
            [
                row
                for row in changes
                if row["change"] < 0
            ],
            key=lambda row: row["change"],
        )[:5]

        entry_score = self._float(
            entry_snapshot.get("overall_institutional_score")
        )
        exit_score = self._float(
            exit_snapshot.get("overall_institutional_score")
        )

        pnl = self._float(realized_pnl)

        if pnl > 0:
            prediction_correct = exit_score > entry_score
        elif pnl < 0:
            prediction_correct = exit_score < entry_score
        else:
            prediction_correct = exit_score == entry_score

        return {
            "trade_id": trade_id,
            "symbol": (symbol or "").upper().strip(),
            "result": (
                "WIN"
                if pnl > 0
                else "LOSS"
                if pnl < 0
                else "FLAT"
            ),
            "realized_pnl": round(pnl, 2),
            "entry_institutional_score": round(entry_score, 2),
            "exit_institutional_score": round(exit_score, 2),
            "institutional_score_change": round(
                exit_score - entry_score,
                2,
            ),
            "strongest_improvements": strongest_improvements,
            "strongest_deteriorations": strongest_deteriorations,
            "institutional_prediction_correct": prediction_correct,
            "status": "INSTITUTIONAL_ATTRIBUTION_COMPLETE",
        }
