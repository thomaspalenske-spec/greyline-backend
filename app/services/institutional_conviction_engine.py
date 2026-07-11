from datetime import datetime

from app.services.institutional_flow_memory_analytics_engine import (
    InstitutionalFlowMemoryAnalyticsEngine,
)


class InstitutionalConvictionEngine:
    """
    Scores how trustworthy the inferred institutional flow is.

    Direction answers: which way is money moving?
    Conviction answers: how much should GreyLine trust that read?
    """

    def _num(self, value, default=50):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def score(
        self,
        option_type,
        setup,
        regime,
        trend,
        equity_flow,
        symbol=None,
    ):
        option_type = str(option_type or "").upper()

        flow_direction = equity_flow.get("institutional_flow_direction")
        flow_confidence = self._num(equity_flow.get("institutional_flow_confidence"), 0)
        context = equity_flow.get("institutional_flow_context") or {}

        try:
            institutional_memory = (
                InstitutionalFlowMemoryAnalyticsEngine()
                .evaluate(symbol)
                if symbol
                else {
                    "symbol": None,
                    "actionable": False,
                    "execution_impact": "OBSERVATION_ONLY",
                    "status": (
                        "INSTITUTIONAL_FLOW_MEMORY_"
                        "SYMBOL_UNAVAILABLE"
                    ),
                }
            )
        except Exception as exc:
            institutional_memory = {
                "symbol": symbol,
                "actionable": False,
                "execution_impact": "OBSERVATION_ONLY",
                "error": repr(exc),
                "status": (
                    "INSTITUTIONAL_FLOW_MEMORY_"
                    "ANALYTICS_DEGRADED"
                ),
            }

        volume_ratio = self._num(context.get("volume_ratio"), 1.0)
        close_location = self._num(context.get("close_location"), 0.5)
        spread_pct = self._num(context.get("spread_pct"), 0.10)
        net_change_pct = abs(self._num(context.get("net_change_pct"), 0))

        if option_type == "CALL":
            setup_score = self._num(setup.get("bullish_setup_score"), setup.get("setup_score", 50))
            regime_score = self._num(regime.get("regime_score"), 50)
            trend_score = self._num(trend.get("trend_persistence_score"), 50)
            directional_close_score = close_location * 100
            flow_aligned = flow_direction in ("INFLOW", "NEUTRAL")
        else:
            setup_score = self._num(setup.get("bearish_setup_score"), 50)
            regime_score = self._num(regime.get("bearish_regime_score"), 50)
            trend_score = self._num(trend.get("bearish_trend_persistence_score"), 50)
            directional_close_score = (1 - close_location) * 100
            flow_aligned = flow_direction in ("OUTFLOW", "NEUTRAL")

        volume_score = min(100, max(0, 50 + (volume_ratio - 1.0) * 35))
        spread_score = 90 if spread_pct <= 0.05 else 70 if spread_pct <= 0.15 else 45
        movement_score = min(100, max(35, 45 + net_change_pct * 10))

        conviction = round(
            flow_confidence * 0.25
            + setup_score * 0.18
            + regime_score * 0.16
            + trend_score * 0.16
            + volume_score * 0.10
            + directional_close_score * 0.08
            + spread_score * 0.04
            + movement_score * 0.03,
            2
        )

        reasons = []
        if flow_aligned:
            reasons.append("FLOW_ALIGNED_WITH_TRADE_DIRECTION")
        else:
            conviction -= 20
            reasons.append("FLOW_MISALIGNED_WITH_TRADE_DIRECTION")

        if volume_ratio >= 1.25:
            reasons.append("ELEVATED_VOLUME_CONFIRMS_PARTICIPATION")
        if spread_pct <= 0.05:
            reasons.append("TIGHT_SPREAD_SUPPORTS_EXECUTION_QUALITY")
        if conviction >= 85:
            state = "HIGH_CONVICTION"
        elif conviction >= 70:
            state = "GOOD_CONVICTION"
        elif conviction >= 55:
            state = "MIXED_CONVICTION"
        else:
            state = "LOW_CONVICTION"

        conviction = round(max(0, min(100, conviction)), 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "option_type": option_type,
            "institutional_conviction_score": conviction,
            "institutional_conviction_state": state,
            "institutional_conviction_reasons": reasons,
            "institutional_conviction_components": {
                "flow_confidence": flow_confidence,
                "setup_score": setup_score,
                "regime_score": regime_score,
                "trend_score": trend_score,
                "volume_score": round(volume_score, 2),
                "directional_close_score": round(directional_close_score, 2),
                "spread_score": spread_score,
                "movement_score": round(movement_score, 2),
                "flow_aligned": flow_aligned,
            },
            "institutional_memory": institutional_memory,
            "institutional_memory_actionable": bool(
                institutional_memory.get(
                    "actionable"
                )
            ),
            "institutional_memory_score": (
                institutional_memory.get(
                    "institutional_memory_score"
                )
            ),
            "institutional_memory_direction": (
                institutional_memory.get(
                    "institutional_memory_direction"
                )
            ),
            "institutional_memory_execution_impact": (
                institutional_memory.get(
                    "execution_impact"
                )
            ),
            "status": "INSTITUTIONAL_CONVICTION_SCORE_READY",
        }
