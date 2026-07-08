class IcebergDetectionEngine:
    def _num(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, tape):
        probability = self._num(tape.get("iceberg_probability"))
        probability = max(0, min(100, probability))

        return {
            "engine": "IcebergDetectionEngine",
            "score": round(probability, 2),
            "detected": probability >= 70,
            "iceberg_probability": round(probability, 2),
            "status": "ICEBERG_DETECTION_READY",
        }
