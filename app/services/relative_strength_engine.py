from datetime import datetime

from app.services.historical_momentum_engine import HistoricalMomentumEngine


class RelativeStrengthEngine:

    def calculate_relative_strength(
        self,
        symbol_score,
        benchmark_score
    ):
        relative_strength = round(
            symbol_score - benchmark_score,
            4
        )

        if relative_strength > 20:
            rs_score = 95
            rs_state = "ELITE_OUTPERFORMANCE"
        elif relative_strength > 10:
            rs_score = 85
            rs_state = "STRONG_OUTPERFORMANCE"
        elif relative_strength > 0:
            rs_score = 70
            rs_state = "OUTPERFORMING"
        elif relative_strength > -10:
            rs_score = 50
            rs_state = "MARKET_PERFORM"
        else:
            rs_score = 25
            rs_state = "UNDERPERFORMING"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "relative_strength": relative_strength,
            "relative_strength_score": rs_score,
            "relative_strength_state": rs_state,
            "execution_enabled": False,
            "status": "RELATIVE_STRENGTH_READY"
        }

    def compare_to_benchmark(self, symbol, benchmark="SPY"):
        symbol_momentum = HistoricalMomentumEngine().calculate_momentum(symbol)
        benchmark_momentum = HistoricalMomentumEngine().calculate_momentum(benchmark)

        return self.calculate_relative_strength(
            symbol_momentum.get("momentum_score", 50),
            benchmark_momentum.get("momentum_score", 50)
        )
