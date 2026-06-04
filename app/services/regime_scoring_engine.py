from datetime import datetime


class RegimeScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        trend_leaders = {
            "NVDA", "META", "MSFT", "AVGO", "QQQ", "SPY"
        }

        volatile_growth = {
            "AMD", "PLTR", "TSLA", "COIN", "MSTR"
        }

        international_semis = {
            "TSM", "SMH"
        }

        if symbol in trend_leaders:
            score = 90
            regime = "TREND_PERSISTENCE"
        elif symbol in volatile_growth:
            score = 78
            regime = "VOLATILE_GROWTH"
        elif symbol in international_semis:
            score = 82
            regime = "SEMI_LEADERSHIP"
        else:
            score = 60
            regime = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "regime_score": score,
            "regime": regime,
            "execution_enabled": False,
            "status": "REGIME_SCORE_READY"
        }
