from datetime import datetime


class ApiSecretRedactionEngine:

    def redact_secret(self, value):

        if not value:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "redacted": None,
                "status": "NO_VALUE"
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "redacted": "****REDACTED****",
            "status": "SECRET_REDACTED"
        }
