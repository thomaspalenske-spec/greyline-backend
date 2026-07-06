from datetime import datetime
from os import getenv


class ApiCredentialReadinessEngine:

    def evaluate_credentials(self):
        api_key_present = bool(getenv("TRADESTATION_API_KEY"))
        api_secret_present = bool(getenv("TRADESTATION_API_SECRET"))
        access_token_present = bool(getenv("TRADESTATION_ACCESS_TOKEN"))
        refresh_token_present = bool(getenv("TRADESTATION_REFRESH_TOKEN"))

        api_credentials_configured = api_key_present and api_secret_present

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "api_credentials_configured": api_credentials_configured,
            "tradestation_client_id_present": api_key_present,
            "tradestation_client_secret_present": api_secret_present,
            "access_token_present": access_token_present,
            "refresh_token_present": refresh_token_present,
            "credential_storage_method": "ENVIRONMENT_VARIABLES" if api_credentials_configured else "NOT_CONFIGURED",
            "safe_to_continue": True,
            "status": "CREDENTIALS_CONFIGURED" if api_credentials_configured else "CREDENTIALS_NOT_CONFIGURED"
        }
