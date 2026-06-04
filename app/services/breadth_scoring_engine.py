from datetime import datetime


class BreadthScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        broad_confirmation = {
            "NVDA", "META", "MSFT", "AVGO", "QQQ", "SPY"
        }

        moderate_confirmation = {
            "AMD", "TSM", "SMH"
        }

        narrow_confirmation = {
            "PLTR", "COIN", "MSTR", "TSLA"
        }

        if symbol in broad_confirmation:
            score = 92
            breadth_state = "BROAD_CONFIRMATION"
        elif symbol in moderate_confirmation:
            score = 82
            breadth_state = "MODERATE_CONFIRMATION"
        elif symbol in narrow_confirmation:
            score = 68
            breadth_state = "NARROW_LEADERSHIP"
        else:
            score = 58
            breadth_state = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "breadth_score": score,
            "breadth_state": breadth_state,
            "execution_enabled": False,
            "status": "BREADTH_SCORE_READY"
        }
