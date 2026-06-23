from datetime import datetime


class BattlefieldAdaptiveWeightAdvisorEngine:
    def evaluate(self, learning):
        sample_count = int(learning.get("sample_count") or 0)
        direction_perf = learning.get("direction_performance") or []
        result_perf = learning.get("candidate_result_performance") or []

        recommendations = []
        warnings = []

        if sample_count < 100:
            warnings.append("INSUFFICIENT_SAMPLE_SIZE_FOR_AUTOMATIC_WEIGHT_CHANGES")

        best_direction = direction_perf[0] if direction_perf else {}
        worst_direction = direction_perf[-1] if direction_perf else {}

        best_result = result_perf[0] if result_perf else {}
        worst_result = result_perf[-1] if result_perf else {}

        if best_direction:
            recommendations.append({
                "type": "DIRECTIONAL_BIAS_OBSERVATION",
                "action": "MONITOR_FOR_WEIGHT_INCREASE",
                "target": best_direction.get("direction"),
                "average_directional_return_pct": best_direction.get("average_directional_return_pct"),
                "samples": best_direction.get("samples"),
            })

        if worst_direction:
            recommendations.append({
                "type": "DIRECTIONAL_BIAS_OBSERVATION",
                "action": "MONITOR_FOR_WEIGHT_DECREASE",
                "target": worst_direction.get("direction"),
                "average_directional_return_pct": worst_direction.get("average_directional_return_pct"),
                "samples": worst_direction.get("samples"),
            })

        if best_result:
            recommendations.append({
                "type": "CANDIDATE_RESULT_OBSERVATION",
                "action": "MONITOR_THRESHOLD_ALIGNMENT",
                "target": best_result.get("candidate_result"),
                "average_directional_return_pct": best_result.get("average_directional_return_pct"),
                "samples": best_result.get("samples"),
            })

        if worst_result:
            recommendations.append({
                "type": "CANDIDATE_RESULT_OBSERVATION",
                "action": "MONITOR_THRESHOLD_TIGHTENING",
                "target": worst_result.get("candidate_result"),
                "average_directional_return_pct": worst_result.get("average_directional_return_pct"),
                "samples": worst_result.get("samples"),
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldAdaptiveWeightAdvisorEngine",
            "mode": "ADVISORY_ONLY",
            "sample_count": sample_count,
            "minimum_samples_for_auto_adjustment": 100,
            "auto_adjustment_enabled": False,
            "warnings": warnings,
            "recommendations": recommendations,
            "status": "BATTLEFIELD_ADAPTIVE_WEIGHT_ADVISOR_READY",
        }
