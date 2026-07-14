from app.services.readiness_aggregation_engine import ReadinessAggregationEngine


class ReadinessFixEngine:
    def evaluate(self):
        data = ReadinessAggregationEngine().evaluate()

        config_registry = data.get("config_registry", [])

        missing = [
            f.get("name")
            for f in config_registry
            if not f.get("is_present", False)
        ]

        recommendations = []

        if "api_key" in missing:
            recommendations.append("Add API key to credentials store")

        if "api_secret" in missing:
            recommendations.append("Add API secret to credentials store")

        if "sandbox_url" in missing:
            recommendations.append("Configure sandbox endpoint URL")

        if "callback_url" in missing:
            recommendations.append("Set webhook/callback URL")

        if "paper_mode" in missing:
            recommendations.append("Enable paper trading mode")

        return {
            # ReadinessAggregationEngine exposes readiness under "status", not "state";
            # the old key never matched and this field was permanently "UNKNOWN".
            "state": data.get("status", "UNKNOWN"),
            "missing_fields": missing,
            "fix_recommendations": recommendations
        }
