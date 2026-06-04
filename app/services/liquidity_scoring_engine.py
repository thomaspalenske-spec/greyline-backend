from datetime import datetime


class LiquidityScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        high_liquidity = {
            "SPY", "QQQ", "NVDA", "MSFT", "AAPL",
            "META", "AMZN", "AMD", "AVGO", "TSLA"
        }

        medium_liquidity = {
            "PLTR", "TSM", "SMH", "IWM", "COIN", "MSTR"
        }

        if symbol in high_liquidity:
            score = 95
            tier = "HIGH"
        elif symbol in medium_liquidity:
            score = 80
            tier = "MEDIUM"
        else:
            score = 60
            tier = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "liquidity_score": score,
            "liquidity_tier": tier,
            "execution_enabled": False,
            "status": "LIQUIDITY_SCORE_READY"
        }
