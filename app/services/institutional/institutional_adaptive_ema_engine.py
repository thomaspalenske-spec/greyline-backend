import json
from pathlib import Path


class InstitutionalAdaptiveEmaEngine:

    DEFAULT_ALPHA = 0.35

    def __init__(self):
        self.path = Path(
            "app/data/institutional/adaptive_ema.json"
        )
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _load(self):
        if not self.path.exists():
            return {}

        try:
            return json.loads(
                self.path.read_text()
            )
        except Exception:
            return {}

    def alpha(self, symbol):
        symbol = (symbol or "").upper()

        data = self._load()

        try:
            value = float(
                data.get(symbol, self.DEFAULT_ALPHA)
            )
        except Exception:
            value = self.DEFAULT_ALPHA

        return min(
            0.90,
            max(
                0.05,
                value,
            ),
        )
