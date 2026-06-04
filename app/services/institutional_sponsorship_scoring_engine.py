from datetime import datetime


class InstitutionalSponsorshipScoringEngine:

    def score_symbol(self, symbol):
        symbol = symbol.upper().strip()

        elite_sponsorship = {
            "NVDA", "META", "MSFT", "AVGO", "QQQ", "SPY"
        }

        strong_sponsorship = {
            "AMD", "TSM", "SMH", "AAPL", "AMZN"
        }

        speculative_sponsorship = {
            "PLTR", "TSLA", "COIN", "MSTR"
        }

        if symbol in elite_sponsorship:
            score = 92
            sponsorship_state = "ELITE_INSTITUTIONAL_SPONSORSHIP"
        elif symbol in strong_sponsorship:
            score = 84
            sponsorship_state = "STRONG_INSTITUTIONAL_SPONSORSHIP"
        elif symbol in speculative_sponsorship:
            score = 70
            sponsorship_state = "SPECULATIVE_SPONSORSHIP"
        else:
            score = 58
            sponsorship_state = "UNKNOWN_DEFAULT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "institutional_sponsorship_score": score,
            "institutional_sponsorship_state": sponsorship_state,
            "execution_enabled": False,
            "status": "INSTITUTIONAL_SPONSORSHIP_SCORE_READY"
        }
