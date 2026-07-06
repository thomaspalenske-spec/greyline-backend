from datetime import datetime


class ForwardOutcomeAttributionEngine:
    def _bucket(self, outcomes, field):
        buckets = {}

        for row in outcomes or []:
            key = row.get(field) or "UNKNOWN"
            successful = row.get("successful")
            directional_return = float(row.get("directional_return_pct") or 0)

            if successful is None:
                continue

            buckets.setdefault(key, {
                field: key,
                "observations": 0,
                "wins": 0,
                "losses": 0,
                "total_directional_return_pct": 0,
            })

            buckets[key]["observations"] += 1
            buckets[key]["total_directional_return_pct"] += directional_return

            if successful:
                buckets[key]["wins"] += 1
            else:
                buckets[key]["losses"] += 1

        rows = []
        for item in buckets.values():
            obs = item["observations"]
            rows.append({
                **item,
                "win_rate_pct": round((item["wins"] / obs) * 100, 2) if obs else 0,
                "average_directional_return_pct": round(item["total_directional_return_pct"] / obs, 4) if obs else 0,
            })

        return sorted(rows, key=lambda x: x["average_directional_return_pct"], reverse=True)

    def evaluate(self, outcomes=None):
        outcomes = outcomes or []

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeAttributionEngine",
            "sample_size": len(outcomes),
            "symbol_attribution": self._bucket(outcomes, "symbol"),
            "direction_attribution": self._bucket(outcomes, "directional_bias"),
            "candidate_result_attribution": self._bucket(outcomes, "candidate_result"),
            "option_type_attribution": self._bucket(outcomes, "option_type"),
            "status": "FORWARD_OUTCOME_ATTRIBUTION_READY",
        }
