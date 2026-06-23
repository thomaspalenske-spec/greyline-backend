from datetime import datetime


class ReadinessHeatmapEngine:
    def evaluate(self, queue):
        rows = []

        for item in queue or []:
            rows.append({
                "symbol": item.get("symbol"),
                "option_type": item.get("option_type"),
                "score": item.get("score"),
                "distance_to_execute": item.get("score_distance_to_execute"),
                "liquidity_score": item.get("liquidity_score"),
                "rank": item.get("rank"),
            })

        rows = sorted(
            rows,
            key=lambda x: (
                x.get("distance_to_execute", 999),
                -(x.get("score") or 0)
            )
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "candidates": rows,
            "status": "READINESS_HEATMAP_READY",
        }
