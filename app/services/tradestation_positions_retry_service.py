from datetime import datetime

from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


class TradeStationPositionsRetryService:

    def get_positions_with_refresh_retry(self):
        first_attempt = TradeStationPositionsLiveEngine().get_positions()

        if first_attempt.get("http_status") != 401:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "first_attempt_status": first_attempt.get("status"),
                "refresh_attempted": False,
                "final_result": first_attempt,
                "execution_enabled": False,
                "status": "POSITIONS_RETRY_NOT_REQUIRED"
            }

        refresh_result = TradeStationTokenRefreshEngine().refresh_access_token()

        if refresh_result.get("status") != "TOKEN_REFRESH_SUCCESS":
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "first_attempt_status": first_attempt.get("status"),
                "refresh_attempted": True,
                "refresh_status": refresh_result.get("status"),
                "execution_enabled": False,
                "status": "POSITIONS_RETRY_REFRESH_FAILED"
            }

        second_attempt = TradeStationPositionsLiveEngine().get_positions()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "first_attempt_status": first_attempt.get("status"),
            "refresh_attempted": True,
            "refresh_status": refresh_result.get("status"),
            "second_attempt_status": second_attempt.get("status"),
            "final_result": second_attempt,
            "execution_enabled": False,
            "status": "POSITIONS_RETRY_SUCCESS"
            if second_attempt.get("http_status") == 200
            else "POSITIONS_RETRY_FAILED"
        }
