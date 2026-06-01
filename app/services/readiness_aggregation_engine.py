from app.services.tradestation_sandbox_readiness_engine import (
    TradeStationSandboxReadinessEngine,
)
from app.services.tradestation_credential_validation_engine import (
    TradeStationCredentialValidationEngine,
)
from app.services.config_registry_engine import ConfigRegistryEngine

from app.services.trade_station_engine import TradeStationEngine
from app.services.config_registry_engine import ConfigRegistryEngine

DEV_MODE = True

class ReadinessAggregationEngine:
    def evaluate(self):
        sandbox = TradeStationSandboxReadinessEngine().evaluate()
        credentials = TradeStationCredentialValidationEngine().evaluate()
        config = ConfigRegistryEngine().evaluate()

        return {
            "system": "GreyLine",
            "status": "ONLINE",
            
            "sandbox_status": sandbox.status,
            "credential_status": credentials.status,

            "config_summary": {
                "total_fields": config["total_fields"],
                "valid_fields": config["valid_fields"],
                "missing_fields": config["total_fields"] - config["valid_fields"],
            },

            "config_registry": config["config_registry"],

            "version": "0.0.3"
        }
