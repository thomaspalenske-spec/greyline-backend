from datetime import datetime


class LearningSampleQualityGateEngine:
    def evaluate(self, learning, grading):
        sample_count = int(learning.get("sample_count") or 0)
        avg_return = float(grading.get("average_directional_return_pct") or 0)
        grade_counts = grading.get("grade_counts") or {}

        warnings = []
        quality_score = 100

        if sample_count < 25:
            warnings.append("VERY_LOW_SAMPLE_SIZE")
            quality_score -= 50
        elif sample_count < 100:
            warnings.append("LOW_SAMPLE_SIZE")
            quality_score -= 30
        elif sample_count < 250:
            warnings.append("MODERATE_SAMPLE_SIZE")
            quality_score -= 10

        flat_count = int(grade_counts.get("FLAT") or 0)
        if sample_count and flat_count / sample_count > 0.25:
            warnings.append("TOO_MANY_FLAT_OUTCOMES")
            quality_score -= 20

        if abs(avg_return) < 0.05:
            warnings.append("WEAK_AVERAGE_DIRECTIONAL_EDGE")
            quality_score -= 20

        quality_score = max(0, min(100, quality_score))

        if quality_score >= 80:
            quality_state = "HIGH_CONFIDENCE_SAMPLE"
        elif quality_score >= 60:
            quality_state = "USABLE_SAMPLE_CAUTION"
        elif quality_score >= 40:
            quality_state = "LOW_CONFIDENCE_SAMPLE"
        else:
            quality_state = "DO_NOT_USE_FOR_ADAPTATION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "LearningSampleQualityGateEngine",
            "sample_count": sample_count,
            "quality_score": quality_score,
            "quality_state": quality_state,
            "warnings": warnings,
            "auto_adaptation_allowed": quality_score >= 80 and sample_count >= 100,
            "status": "LEARNING_SAMPLE_QUALITY_GATE_READY",
        }
