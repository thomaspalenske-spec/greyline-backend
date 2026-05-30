from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class TradeStationSandboxReadinessResult:
    status: str
    api_key_present: bool
    api_secret_present: bool
    sandbox_base_url_present: bool
    callback_url_present: bool
    paper_trading_mode: bool
    message: str


class TradeStationSandboxReadinessEngine:
    REQUIRED_ENV_KEYS = {
        "api_key": "TRADESTATION_API_KEY",
        "api_secret": "TRADESTATION_API_SECRET",
        "sandbox_base_url": "TRADESTATION_SANDBOX_BASE_URL",
        "callback_url": "TRADESTATION_CALLBACK_URL",
        "paper_mode": "TRADESTATION_PAPER_MODE",
    }

    def evaluate(self) -> TradeStationSandboxReadinessResult:
        api_key_present = bool(getenv(self.REQUIRED_ENV_KEYS["api_key"]))
        api_secret_present = bool(getenv(self.REQUIRED_ENV_KEYS["api_secret"]))
        sandbox_base_url_present = bool(getenv(self.REQUIRED_ENV_KEYS["sandbox_base_url"]))
        callback_url_present = bool(getenv(self.REQUIRED_ENV_KEYS["callback_url"]))
        paper_trading_mode = getenv(self.REQUIRED_ENV_KEYS["paper_mode"], "").lower() in {
            "true",
            "1",
            "yes",
            "paper",
            "sandbox",
        }

        ready = all(
            [
                api_key_present,
                api_secret_present,
                sandbox_base_url_present,
                callback_url_present,
                paper_trading_mode,
            ]
        )

        return TradeStationSandboxReadinessResult(
            status="READY" if ready else "NOT_READY",
            api_key_present=api_key_present,
            api_secret_present=api_secret_present,
            sandbox_base_url_present=sandbox_base_url_present,
            callback_url_present=callback_url_present,
            paper_trading_mode=paper_trading_mode,
            message=(
                "TradeStation sandbox readiness gate passed."
                if ready
                else "TradeStation sandbox readiness gate failed. Missing required sandbox configuration."
            ),
        )
