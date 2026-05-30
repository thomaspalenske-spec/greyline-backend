from datetime import datetime


class BrokerAuthorityGateEngine:

    ALLOWED_AUTHORITY_LEVELS = [
        "OBSERVE_ONLY",
        "OBSERVE_RECOMMEND_ONLY"
    ]

    def evaluate_authority(self, requested_authority_level):

        allowed = requested_authority_level in self.ALLOWED_AUTHORITY_LEVELS

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "requested_authority_level": requested_authority_level,
            "allowed_authority_levels": self.ALLOWED_AUTHORITY_LEVELS,
            "authority_approved": allowed,
            "execution_blocked": not allowed
        }
