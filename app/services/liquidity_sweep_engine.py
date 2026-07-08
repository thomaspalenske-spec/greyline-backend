class LiquiditySweepEngine:
    def _num(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    def evaluate(self, tape):
        sweeps = self._num(tape.get("sweeps") or tape.get("sweep_count"))
        score = round(max(0, min(100, sweeps * 20)), 2)

        return {
            "engine": "LiquiditySweepEngine",
            "score": score,
            "detected": sweeps > 0,
            "events": sweeps,
            "status": "LIQUIDITY_SWEEP_READY",
        }
