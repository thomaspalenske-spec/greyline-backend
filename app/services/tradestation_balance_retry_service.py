from datetime import datetime

from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


class TradeStationBalanceRetryService:

    def get_balance_with_refresh_retry(self):
        first_attempt = TradeStationBalanceLiveEngine().get_balance()

        if first_attempt.get("http_status") != 401:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "first_attempt_status": first_attempt.get("status"),
                "refresh_attempted": False,
                "final_result": first_attempt,
                "execution_enabled": False,
                "status": "BALANCE_RETRY_NOT_REQUIRED"
            }

        refresh_result = TradeStationTokenRefreshEngine().refresh()

        if refresh_result.get("status") != "TOKEN_REFRESH_SUCCESS":
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "first_attempt_status": first_attempt.get("status"),
                "refresh_attempted": True,
                "refresh_status": refresh_result.get("status"),
                "execution_enabled": False,
                "status": "BALANCE_RETRY_REFRESH_FAILED"
            }

        second_attempt = TradeStationBalanceLiveEngine().get_balance()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "first_attempt_status": first_attempt.get("status"),
            "refresh_attempted": True,
            "refresh_status": refresh_result.get("status"),
            "second_attempt_status": second_attempt.get("status"),
            "final_result": second_attempt,
            "execution_enabled": False,
            "status": "BALANCE_RETRY_SUCCESS" if second_attempt.get("http_status") == 200 else "BALANCE_RETRY_FAILED"
        }
