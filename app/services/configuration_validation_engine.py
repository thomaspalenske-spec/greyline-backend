from datetime import datetime


class ConfigurationValidationEngine:

    REQUIRED_CONFIG_KEYS = [
        "GREYLINE_MODE",
        "GREYLINE_ENVIRONMENT",
        "BROKER_CONNECTION_ENABLED",
        "AUTONOMOUS_EXECUTION_ENABLED"
    ]

    def validate_configuration(self, config_values):

        missing_keys = [
            key for key in self.REQUIRED_CONFIG_KEYS
            if key not in config_values
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "required_keys": self.REQUIRED_CONFIG_KEYS,
            "missing_keys": missing_keys,
            "configuration_valid": len(missing_keys) == 0,
            "secrets_exposed": False,
            "status": "CONFIGURATION_VALID" if len(missing_keys) == 0 else "CONFIGURATION_INCOMPLETE"
        }
