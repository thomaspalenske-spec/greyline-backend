from datetime import datetime


class OpportunityQueueEngine:
    def build(self, battlefield):
        rows = []

        for key, option_type in [("best_call", "CALL"), ("best_put", "PUT")]:
            item = battlefield.get(key, {}) or {}
            if not item:
                continue

            score = float(item.get("composite_score") or item.get("score") or 0)

            raw_liquidity = item.get("liquidity_score")
            liquidity_available = raw_liquidity is not None
            liquidity = float(raw_liquidity) if liquidity_available else None

            rows.append({
                "symbol": item.get("symbol"),
                "option_type": option_type,
                "result": item.get("result"),
                "score": score,
                "liquidity_score": liquidity,
                "liquidity_status": "AVAILABLE" if liquidity_available else "UNAVAILABLE",
                "execute_score_threshold": 85,
                "execute_liquidity_threshold": 70,
                "score_distance_to_execute": round(max(85 - score, 0), 2),
                "liquidity_distance_to_execute": round(max(70 - liquidity, 0), 2) if liquidity_available else None,
                "directional_bias": item.get("directional_bias"),
                "setup_score": item.get("setup_score"),
                "direction_confidence": item.get("direction_confidence"),
            })

        rows = sorted(
            rows,
            key=lambda x: (
                x["score_distance_to_execute"],
                x["liquidity_distance_to_execute"] if x["liquidity_distance_to_execute"] is not None else 999,
                -x["score"],
            )
        )

        for i, row in enumerate(rows, 1):
            row["rank"] = i

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OpportunityQueueEngine",
            "queue": rows,
            "top_candidate": rows[0] if rows else None,
            "status": "OPPORTUNITY_QUEUE_READY",
        }
