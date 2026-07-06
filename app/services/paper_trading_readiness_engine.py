from dataclasses import asdict, is_dataclass
from datetime import datetime
from os import getenv

from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine
from app.services.tradestation_sandbox_readiness_engine import TradeStationSandboxReadinessEngine
from app.services.position_reconciliation_engine import PositionReconciliationEngine


class PaperTradingReadinessEngine:

    def evaluate_readiness(self):
        api = ApiCredentialReadinessEngine().evaluate_credentials()
        sandbox_raw = TradeStationSandboxReadinessEngine().evaluate()
        sandbox = asdict(sandbox_raw) if is_dataclass(sandbox_raw) else sandbox_raw
        reconciliation = PositionReconciliationEngine().reconcile_positions()

        api_credentials_configured = (
            api.get("api_credentials_configured") is True
            or api.get("api_credentials_ready") is True
            or api.get("credentials_ready") is True
            or api.get("status") in [
                "CREDENTIALS_CONFIGURED",
                "API_CREDENTIALS_READY",
                "CREDENTIALS_READY",
            ]
        )

        broker_sandbox_connected = (
            sandbox.get("sandbox_connected") is True
            or sandbox.get("connected") is True
            or sandbox.get("status") in ["READY", "TRADESTATION_SANDBOX_READY", "SANDBOX_CONNECTED"]
        )

        paper_account_verified = (
            sandbox.get("paper_account_verified") is True
            or sandbox.get("paper_trading_account_verified") is True
            or broker_sandbox_connected
        )

        reconciliation_testing_complete = (
            reconciliation.get("reconciliation_status") == "PASS"
        )

        kill_switch_testing_complete = (
            getenv("GREYLINE_KILL_SWITCH_TESTED", "false").lower() == "true"
        )

        manual_approval_granted = (
            getenv("GREYLINE_PAPER_TRADING_APPROVED", "false").lower() == "true"
        )

        paper_trading_ready = all([
            api_credentials_configured,
            paper_account_verified,
            broker_sandbox_connected,
            reconciliation_testing_complete,
            kill_switch_testing_complete,
            manual_approval_granted,
        ])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "backend_ready": True,
            "broker_prep_roadmap_active": True,
            "api_credentials_configured": api_credentials_configured,
            "paper_account_verified": paper_account_verified,
            "broker_sandbox_connected": broker_sandbox_connected,
            "reconciliation_testing_complete": reconciliation_testing_complete,
            "kill_switch_testing_complete": kill_switch_testing_complete,
            "manual_approval_granted": manual_approval_granted,
            "authority_level": (
                "PAPER_TRADING_APPROVED"
                if manual_approval_granted
                else "OBSERVE_RECOMMEND_ONLY"
            ),
            "paper_trading_ready": paper_trading_ready,
            "api_credential_readiness": api,
            "sandbox_readiness": sandbox,
            "reconciliation": reconciliation,
            "status": (
                "PAPER_TRADING_READY"
                if paper_trading_ready
                else "PAPER_TRADING_NOT_READY"
            ),
        }
