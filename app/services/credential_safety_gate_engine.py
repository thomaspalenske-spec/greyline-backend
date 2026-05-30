from datetime import datetime


class CredentialSafetyGateEngine:

    def evaluate_credential_safety(
        self,
        credentials_in_plaintext,
        env_file_present,
        gitignore_protects_env,
        credential_rotation_required
    ):

        safe = (
            not credentials_in_plaintext
            and env_file_present
            and gitignore_protects_env
            and not credential_rotation_required
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "credentials_in_plaintext": credentials_in_plaintext,
            "env_file_present": env_file_present,
            "gitignore_protects_env": gitignore_protects_env,
            "credential_rotation_required": credential_rotation_required,
            "credential_safety_approved": safe,
            "status": "CREDENTIAL_SAFE" if safe else "CREDENTIAL_BLOCKED"
        }
