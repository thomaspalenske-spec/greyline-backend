import os
from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class ConfigField:
    name: str
    value: str
    is_present: bool


class ConfigRegistryEngine:
    REQUIRED_FIELDS = {
        "TRADESTATION_API_KEY": "api_key",
        "TRADESTATION_API_SECRET": "api_secret",
        "TRADESTATION_SANDBOX_BASE_URL": "sandbox_url",
        "TRADESTATION_CALLBACK_URL": "callback_url",
        "TRADESTATION_PAPER_MODE": "paper_mode",
    }

    def evaluate(self):
        registry = []

        for env_key, label in self.REQUIRED_FIELDS.items():
            value = getenv(env_key, "")
            registry.append(
                ConfigField(
                    name=label,
                    value="SET" if value else "DEV_VALUE",
                    is_present=True if os.getenv("DEV_MODE") == "true" else bool(value),
                )
            )

        return {
            "config_registry": [f.__dict__ for f in registry],
            "total_fields": len(registry),
            "valid_fields": sum(1 for f in registry if (os.getenv("DEV_MODE") == "true" or f.is_present)),
        }
