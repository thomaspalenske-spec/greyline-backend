from datetime import datetime


class VolatilityScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        stable_leaders = {
            "NVDA", "META", "MSFT", "AVGO"
        }

        moderate_volatility = {
            "AMD", "TSM", "QQQ", "SPY"
        }

        high_volatility = {
            "PLTR", "TSLA", "COIN", "MSTR"
        }

        if symbol in stable_leaders:
            score = 92
            volatility_state = "STABLE_LEADERSHIP"
        elif symbol in moderate_volatility:
            score = 82
            volatility_state = "MODERATE_VOLATILITY"
        elif symbol in high_volatility:
            score = 68
            volatility_state = "HIGH_VOLATILITY"
        else:
            score = 60
            volatility_state = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "volatility_score": score,
            "volatility_state": volatility_state,
            "execution_enabled": False,
            "status": "VOLATILITY_SCORE_READY"
        }
