from datetime import datetime


class TrendPersistenceScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        elite_trend = {
            "NVDA", "META", "MSFT", "AVGO"
        }

        strong_trend = {
            "AMD", "TSM", "QQQ", "SPY"
        }

        unstable_trend = {
            "PLTR", "TSLA", "COIN", "MSTR"
        }

        if symbol in elite_trend:
            score = 93
            trend_state = "ELITE_TREND_PERSISTENCE"
        elif symbol in strong_trend:
            score = 84
            trend_state = "STRONG_TREND_PERSISTENCE"
        elif symbol in unstable_trend:
            score = 70
            trend_state = "UNSTABLE_TREND"
        else:
            score = 58
            trend_state = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "trend_persistence_score": score,
            "trend_state": trend_state,
            "execution_enabled": False,
            "status": "TREND_PERSISTENCE_SCORE_READY"
        }
