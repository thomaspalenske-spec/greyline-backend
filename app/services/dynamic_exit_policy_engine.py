from datetime import datetime

from app.services.volatility_scoring_engine import VolatilityScoringEngine


class DynamicExitPolicyEngine:
    """
    Converts live volatility context into symbol-specific paper trade exits.
    Higher volatility gets more room. Targets are derived from stop distance.
    """

    def build_policy(self, symbol, composite_score=None):
        vol = VolatilityScoringEngine().score_symbol(symbol)
        volatility_score = float(vol.get("volatility_score", 50))

        # Continuous volatility-adjusted stop:
        # volatility_score 100 -> -3.0%
        # volatility_score 0   -> -7.0%
        # This prevents AMD/NVDA from receiving identical exits just because
        # they fall in the same broad bucket.
        stop_loss_pct = -round(3.0 + ((100.0 - volatility_score) / 100.0) * 4.0, 2)

        if volatility_score >= 85:
            volatility_band = "CONTROLLED"
        elif volatility_score >= 70:
            volatility_band = "ELEVATED"
        elif volatility_score >= 50:
            volatility_band = "HIGH"
        else:
            volatility_band = "EXTREME"

        if composite_score is None:
            reward_multiple = 2.0
        elif composite_score >= 90:
            reward_multiple = 2.75
        elif composite_score >= 80:
            reward_multiple = 2.5
        elif composite_score >= 70:
            reward_multiple = 2.25
        else:
            reward_multiple = 2.0

        take_profit_pct = abs(stop_loss_pct) * reward_multiple

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "exit_policy": "DYNAMIC_VOLATILITY_REWARD_RISK",
            "volatility_score": volatility_score,
            "volatility_state": vol.get("volatility_state"),
            "volatility_band": volatility_band,
            "volatility_reasons": vol.get("volatility_reasons", []),
            "stop_loss_pct": round(stop_loss_pct, 2),
            "reward_multiple": round(reward_multiple, 2),
            "take_profit_pct": round(take_profit_pct, 2),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DYNAMIC_EXIT_POLICY_READY",
        }
