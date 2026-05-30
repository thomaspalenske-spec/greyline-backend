from datetime import datetime


class BrokerSandboxConnectionPlanEngine:

    def get_plan(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "connection_target": "TRADESTATION_SANDBOX_OR_PAPER",
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "autonomous_execution_enabled": False,
            "steps": [
                "Confirm paper trading account exists",
                "Confirm API credentials are stored outside source code",
                "Confirm .env is protected by .gitignore",
                "Load credentials through environment variables only",
                "Connect to broker sandbox read-only endpoints first",
                "Verify account balance read access",
                "Verify position read access",
                "Verify order-history read access",
                "Run reconciliation against broker data",
                "Keep execution disabled until explicit approval"
            ],
            "status": "SANDBOX_CONNECTION_PLAN_ACTIVE"
        }
