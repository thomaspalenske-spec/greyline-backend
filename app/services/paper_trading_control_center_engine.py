from datetime import datetime


class PaperTradingControlCenterEngine:

    def get_control_center(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_ready": False,
            "paper_trading_blocked": True,
            "approval_passed": False,
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "broker_connected": False,
            "api_credentials_configured": False,
            "next_state": "PAPER_TRADING_BLOCKED",
            "status": "PAPER_TRADING_CONTROL_CENTER_ACTIVE"
        }
