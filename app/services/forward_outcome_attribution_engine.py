from datetime import datetime


class ForwardOutcomeAttributionEngine:
    def evaluate(self, outcomes=None):
        outcomes = outcomes or []

        components = {}

        for row in outcomes:
            component = row.get("component")
            successful = bool(row.get("successful"))

            if not component:
                continue

            if component not in components:
                components[component] = {
                    "component": component,
                    "observations": 0,
                    "wins": 0,
                    "losses": 0,
                }

            components[component]["observations"] += 1

            if successful:
                components[component]["wins"] += 1
            else:
                components[component]["losses"] += 1

        rankings = []

        for item in components.values():
            obs = item["observations"]

            predictive_power = (
                round(item["wins"] / obs, 4)
                if obs
                else 0
            )

            rankings.append({
                **item,
                "predictive_power": predictive_power,
            })

        rankings.sort(
            key=lambda x: x["predictive_power"],
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeAttributionEngine",
            "components": rankings,
            "component_count": len(rankings),
            "status": "FORWARD_OUTCOME_ATTRIBUTION_READY",
        }
