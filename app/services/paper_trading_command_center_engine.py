from datetime import datetime

from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine
from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine


class PaperTradingCommandCenterEngine:

    def get_command_center(self):
        # broker_connected / api_credentials_configured are FACTUAL fields — derive
        # them from the real engines (same as the control center). The remaining gate
        # fields below stay as deliberate human-controlled arming gates.
        reliability = GreyLineReliabilityCoreEngine().evaluate()
        credentials = ApiCredentialReadinessEngine().evaluate_credentials()

        checks = reliability.get("checks", {})
        broker_connected = bool(checks.get("balance_ok")) and bool(checks.get("positions_ok"))
        api_credentials_configured = bool(credentials.get("api_credentials_configured"))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_ready": False,
            "paper_trading_blocked": True,
            "approval_passed": False,
            "launch_checklist_complete": False,
            "final_gate_passed": False,
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "broker_connected": broker_connected,
            "api_credentials_configured": api_credentials_configured,
            "next_state": "PAPER_TRADING_ALLOWED",
            "status": "PAPER_TRADING_COMMAND_CENTER_ACTIVE"
        }
