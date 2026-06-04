from datetime import datetime


class RiskStateScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        normal_risk_assets = {
            "NVDA", "META", "MSFT", "AVGO", "QQQ", "SPY"
        }

        elevated_risk_assets = {
            "AMD", "TSM", "PLTR", "TSLA", "COIN", "MSTR"
        }

        if symbol in normal_risk_assets:
            score = 92
            risk_state = "NORMAL"
        elif symbol in elevated_risk_assets:
            score = 78
            risk_state = "ELEVATED"
        else:
            score = 60
            risk_state = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "risk_state_score": score,
            "risk_state": risk_state,
            "execution_enabled": False,
            "status": "RISK_STATE_SCORE_READY"
        }
