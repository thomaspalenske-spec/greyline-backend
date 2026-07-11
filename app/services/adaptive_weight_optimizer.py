from pathlib import Path
import json
from datetime import datetime

WEIGHTS_FILE = Path("app/data/adaptive_weights.json")

FACTORS = [
    "breadth_score",
    "setup_score",
    "risk_state_score",
    "regime_score",
    "institutional_sponsorship_score",
    "volatility_score",
    "liquidity_score",
    "direction_confidence",
    "forecast_confidence",
]

MIN_SAMPLE = 50
MIN_WEIGHT = 0.75
MAX_WEIGHT = 1.30
MAX_STEP = 0.02


class AdaptiveWeightOptimizer:

    def load(self):
        if WEIGHTS_FILE.exists():
            return json.loads(WEIGHTS_FILE.read_text())
        return {}

    def save(self, data):
        WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        WEIGHTS_FILE.write_text(
            json.dumps(data, indent=2, sort_keys=True)
        )

    def optimize(self, attribution):

        previous = self.load()
        learned = {}

        for factor in FACTORS:

            d = attribution.get(factor, {})

            sample = d.get("sample_size", 0)

            if sample < MIN_SAMPLE:
                learned[factor] = previous.get(
                    factor,
                    {"weight": 1.0}
                )
                continue

            wr = d.get("win_rate", 50)

            target = (
                1.30 if wr >= 80 else
                1.20 if wr >= 70 else
                1.10 if wr >= 60 else
                1.00 if wr >= 50 else
                0.90 if wr >= 40 else
                0.80
            )

            current = previous.get(
                factor,
                {"weight": 1.0}
            )["weight"]

            if target > current:
                target = min(target, current + MAX_STEP)
            else:
                target = max(target, current - MAX_STEP)

            target = max(
                MIN_WEIGHT,
                min(MAX_WEIGHT, target)
            )

            learned[factor] = {
                "weight": round(target, 3),
                "sample_size": sample,
                "win_rate": wr,
                "updated": datetime.utcnow().isoformat(),
            }

        self.save(learned)
        return learned
