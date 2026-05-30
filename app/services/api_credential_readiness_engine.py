from datetime import datetime


class ApiCredentialReadinessEngine:

    def evaluate_credentials(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "api_credentials_configured": False,
            "tradestation_client_id_present": False,
            "tradestation_client_secret_present": False,
            "access_token_present": False,
            "refresh_token_present": False,
            "credential_storage_method": "NOT_CONFIGURED",
            "safe_to_continue": True,
            "status": "CREDENTIALS_NOT_CONFIGURED"
        }
