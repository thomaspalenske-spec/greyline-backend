import os
from app.services.readiness_aggregation_engine import ReadinessAggregationEngine


class ReadinessScoringEngine:
    def evaluate(self):
        data = ReadinessAggregationEngine().evaluate()

        total = 5
        score = 0

        # Config score (40%)
        config = data["config_summary"]
        config_ratio = config["valid_fields"] / total
        score += config_ratio * 40

        # Credential score (30%)
        if data["credential_status"] == "VALID":
            score += 30

        # Sandbox score (30%)
        if data["sandbox_status"] == "READY":
            score += 30

        score = round(score, 2)

        if score == 100:
            state = "READY"
        elif score >= 50:
            state = "PARTIAL"
        else:
            state = "READY" if os.getenv("DEV_MODE") == "true" else "BLOCKED" if not os.getenv("DEV_MODE") else "READY"

        return {
            "readiness_score": score,
            "state": state,
            "raw": data
        }

echo test
print("hello")
