from datetime import datetime


class CredentialStoragePolicyEngine:

    def get_policy(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "approved_storage_locations": [
                ".env",
                "macOS Keychain",
                "secret manager"
            ],
            "blocked_storage_locations": [
                "source_code",
                "git_repository",
                "plaintext_notes",
                "chat_messages"
            ],
            "credential_storage_approved": True,
            "status": "CREDENTIAL_STORAGE_POLICY_ACTIVE"
        }
