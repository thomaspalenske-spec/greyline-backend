from datetime import datetime


class SetupScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        elite_setups = {
            "NVDA", "META", "MSFT", "AVGO"
        }

        strong_setups = {
            "AMD", "TSM", "QQQ", "SPY"
        }

        developing_setups = {
            "PLTR", "AMZN", "SMH", "IWM"
        }

        if symbol in elite_setups:
            score = 90
            setup_tier = "ELITE"
        elif symbol in strong_setups:
            score = 82
            setup_tier = "STRONG"
        elif symbol in developing_setups:
            score = 72
            setup_tier = "DEVELOPING"
        else:
            score = 55
            setup_tier = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "setup_score": score,
            "setup_tier": setup_tier,
            "execution_enabled": False,
            "status": "SETUP_SCORE_READY"
        }
