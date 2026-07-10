from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json


class InstitutionalAttributionEngine:
    """
    Attributes trade decisions to contributing GreyLine engines.

    Observation only.
    Does not modify execution decisions.
    """

    DATA_DIR = Path("app/data/institutional_attribution")
    TRADE_LOG = DATA_DIR / "trades.jsonl"
    ENGINE_SCORE_FILE = DATA_DIR / "engine_scores.json"

    ENGINE_FIELDS = {
        "trend": "trend_persistence_score",
        "liquidity": "liquidity_score",
        "risk": "risk_state_score",
        "regime": "regime_score",
        "institutional": "institutional_sponsorship_score",
        "direction": "direction_confidence",
        "setup": "setup_score",
    }

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _safe_float(self, value):
        try:
            return float(value)
        except Exception:
            return 0.0

    def attribute(self, candidate: dict) -> dict:

        total = 0.0
        raw = {}

        for engine, field in self.ENGINE_FIELDS.items():
            score = self._safe_float(candidate.get(field))
            raw[engine] = score
            total += max(score, 0)

        contributions = {}

        if total > 0:
            for engine, score in raw.items():
                contributions[engine] = round(
                    score / total * 100,
                    2,
                )
        else:
            for engine in raw:
                contributions[engine] = 0.0

        ordered = sorted(
            contributions.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        result = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "symbol": candidate.get("symbol"),
            "composite_score": candidate.get("composite_score"),
            "result": candidate.get("result"),
            "engine_contributions": contributions,
            "top_contributors": ordered[:3],
            "status": "INSTITUTIONAL_ATTRIBUTION_READY",
        }

        with self.TRADE_LOG.open("a") as f:
            f.write(json.dumps(result) + "\n")

        return result
