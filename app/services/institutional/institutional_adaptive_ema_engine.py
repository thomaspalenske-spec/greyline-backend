import json
from pathlib import Path


class InstitutionalAdaptiveEmaEngine:

    DEFAULT_ALPHA = 0.35
    MIN_ALPHA = 0.05
    MAX_ALPHA = 0.90
    MIN_VERIFIED_FORECASTS = 25

    PROFILE_PATH = Path(
        "app/data/institutional/adaptive_ema_profiles.json"
    )

    CANDIDATE_ALPHAS = [
        0.10,
        0.15,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.45,
        0.50,
        0.55,
        0.60,
    ]

    def __init__(self):
        self.path = self.PROFILE_PATH
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _load(self):
        if not self.path.exists():
            return {}

        try:
            data = json.loads(
                self.path.read_text()
            )
        except Exception:
            return {}

        return (
            data
            if isinstance(data, dict)
            else {}
        )

    def save_profiles(
        self,
        profiles,
    ):
        profiles = (
            profiles
            if isinstance(profiles, dict)
            else {}
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.path.write_text(
            json.dumps(
                profiles,
                indent=2,
                sort_keys=True,
            )
        )

    def candidate_alphas(self):
        return list(
            self.CANDIDATE_ALPHAS
        )

    def alpha(self, symbol):
        symbol = (
            symbol
            or ""
        ).upper().strip()

        data = self._load()

        profile = data.get(
            symbol,
            self.DEFAULT_ALPHA,
        )

        if isinstance(profile, dict):
            profile = profile.get(
                "alpha",
                self.DEFAULT_ALPHA,
            )

        try:
            value = float(profile)
        except Exception:
            value = self.DEFAULT_ALPHA

        return min(
            self.MAX_ALPHA,
            max(
                self.MIN_ALPHA,
                value,
            ),
        )
