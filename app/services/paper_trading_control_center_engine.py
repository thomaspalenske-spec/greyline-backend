from datetime import datetime

from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine
from app.services.api_credential_readiness_engine import ApiCredentialReadinessEngine


class PaperTradingControlCenterEngine:

    def get_control_center(self):
        # Reuse the reliability core as the single source of truth for broker
        # connectivity, and the credential readiness engine for credential config.
        # These two fields are FACTUAL (is the broker reachable / are creds set),
        # not governance decisions. The gating fields below (ready/blocked/approval/
        # authority) remain deliberate human-controlled arming gates.
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
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "broker_connected": broker_connected,
            "api_credentials_configured": api_credentials_configured,
            "next_state": "PAPER_TRADING_ALLOWED",
            "status": "PAPER_TRADING_CONTROL_CENTER_ACTIVE"
        }
