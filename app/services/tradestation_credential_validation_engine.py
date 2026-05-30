from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class CredentialValidationResult:
    status: str
    api_key_valid: bool
    api_secret_valid: bool
    message: str


class TradeStationCredentialValidationEngine:
    API_KEY_ENV = "TRADESTATION_API_KEY"
    API_SECRET_ENV = "TRADESTATION_API_SECRET"

    def evaluate(self) -> CredentialValidationResult:
        api_key = getenv(self.API_KEY_ENV, "")
        api_secret = getenv(self.API_SECRET_ENV, "")

        api_key_valid = len(api_key.strip()) > 10
        api_secret_valid = len(api_secret.strip()) > 10

        valid = api_key_valid and api_secret_valid

        return CredentialValidationResult(
            status="VALID" if valid else "INVALID",
            api_key_valid=api_key_valid,
            api_secret_valid=api_secret_valid,
            message=(
                "Credential structure validation passed."
                if valid
                else "Credential structure validation failed."
            ),
        )
