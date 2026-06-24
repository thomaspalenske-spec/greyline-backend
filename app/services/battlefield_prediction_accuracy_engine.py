from datetime import datetime


class BattlefieldPredictionAccuracyEngine:
    def evaluate(self, outcomes=None):
        outcomes = outcomes or []
        scored = []

        for item in outcomes or []:
            snapshot = float(item.get("snapshot_price") or 0)
            current = float(item.get("current_price") or 0)
            bias = item.get("directional_bias")

            if snapshot <= 0 or current <= 0 or bias not in ["BULLISH", "BEARISH"]:
                continue

            move_pct = round(((current / snapshot) - 1) * 100, 4)

            if bias == "BULLISH":
                correct = current > snapshot
            else:
                correct = current < snapshot

            scored.append({
                "symbol": item.get("symbol"),
                "directional_bias": bias,
                "candidate_result": item.get("candidate_result"),
                "snapshot_price": snapshot,
                "current_price": current,
                "move_pct": move_pct,
                "prediction_correct": correct,
            })

        correct_count = len([x for x in scored if x.get("prediction_correct")])
        incorrect_count = len(scored) - correct_count

        accuracy = round((correct_count / len(scored)) * 100, 2) if scored else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldPredictionAccuracyEngine",
            "evaluated_predictions": len(scored),
            "correct_predictions": correct_count,
            "incorrect_predictions": incorrect_count,
            "accuracy_pct": accuracy,
            "predictions": scored[-25:],
            "status": "BATTLEFIELD_PREDICTION_ACCURACY_READY",
        }
