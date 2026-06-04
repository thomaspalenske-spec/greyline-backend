from datetime import datetime


class ExpectedValueScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        elite_ev = {
            "NVDA", "META", "MSFT", "AVGO"
        }

        strong_ev = {
            "AMD", "TSM", "QQQ", "SPY"
        }

        developing_ev = {
            "PLTR", "AMZN", "SMH", "IWM"
        }

        if symbol in elite_ev:
            score = 92
            ev_tier = "ELITE_EXPECTED_VALUE"
        elif symbol in strong_ev:
            score = 84
            ev_tier = "STRONG_EXPECTED_VALUE"
        elif symbol in developing_ev:
            score = 74
            ev_tier = "DEVELOPING_EXPECTED_VALUE"
        else:
            score = 58
            ev_tier = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "expected_value_score": score,
            "expected_value_tier": ev_tier,
            "execution_enabled": False,
            "status": "EXPECTED_VALUE_SCORE_READY"
        }
