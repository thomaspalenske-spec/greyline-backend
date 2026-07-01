from datetime import datetime

from app.services.opportunity_summary_engine import OpportunitySummaryEngine


class DirectionalAttributionReportEngine:
    EXECUTE_THRESHOLD = 85.0

    WEIGHTS = {
        "market_data_score": 0.08,
        "liquidity_score": 0.11,
        "setup": 0.13,
        "regime": 0.11,
        "volatility_score": 0.07,
        "expected_value": 0.10,
        "trend": 0.09,
        "breadth": 0.08,
        "sponsorship": 0.08,
        "asymmetry": 0.08,
        "risk_state_score": 0.07,
    }

    def run(self, limit=100):
        rows = OpportunitySummaryEngine().get_summary(limit=limit).get("opportunities", [])

        analyzed = [self._analyze(r) for r in rows]
        calls = [x for x in analyzed if x.get("option_type") == "CALL"]
        puts = [x for x in analyzed if x.get("option_type") == "PUT"]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "DirectionalAttributionReportEngine",
            "total_candidates": len(analyzed),
            "call_count": len(calls),
            "put_count": len(puts),
            "call_execute": len([x for x in calls if x.get("result") == "EXECUTE"]),
            "put_execute": len([x for x in puts if x.get("result") == "EXECUTE"]),
            "top_calls": calls[:10],
            "top_puts": puts[:10],
            "status": "DIRECTIONAL_ATTRIBUTION_READY",
        }

    def _analyze(self, r):
        option_type = r.get("option_type")
        score = float(r.get("composite_score") or 0)
        distance = round(max(self.EXECUTE_THRESHOLD - score, 0), 2)

        if option_type == "PUT":
            component_scores = {
                "market_data_score": r.get("market_data_score", 100),
                "liquidity_score": r.get("liquidity_score"),
                "setup": r.get("bearish_setup_score", r.get("setup_score")),
                "regime": r.get("bear_regime_score", 100 - self._num(r.get("regime_score"))),
                "volatility_score": r.get("volatility_score", 50),
                "expected_value": r.get("bear_expected_value_score", max(45, 100 - self._num(r.get("expected_value_score")))),
                "trend": r.get("bear_trend_score", 100 - self._num(r.get("trend_persistence_score"))),
                "breadth": r.get("bear_breadth_score", max(35, 100 - self._num(r.get("breadth_score")))),
                "sponsorship": r.get("bear_sponsorship_score", 100 - self._num(r.get("institutional_sponsorship_score"))),
                "asymmetry": r.get("bear_asymmetry_score", 100 - self._num(r.get("asymmetry_score"))),
                "risk_state_score": r.get("risk_state_score", 75),
            }
        else:
            component_scores = {
                "market_data_score": r.get("market_data_score", 100),
                "liquidity_score": r.get("liquidity_score"),
                "setup": r.get("bullish_setup_score", r.get("setup_score")),
                "regime": r.get("regime_score"),
                "volatility_score": r.get("volatility_score", 50),
                "expected_value": r.get("expected_value_score"),
                "trend": r.get("trend_persistence_score"),
                "breadth": r.get("breadth_score"),
                "sponsorship": r.get("institutional_sponsorship_score"),
                "asymmetry": r.get("asymmetry_score"),
                "risk_state_score": r.get("risk_state_score", 75),
            }

        contributions = []
        for name, raw in component_scores.items():
            raw = self._num(raw)
            weight = self.WEIGHTS.get(name, 0)
            contribution = round(raw * weight, 2)
            max_contribution = round(100 * weight, 2)
            gap_to_max = round(max_contribution - contribution, 2)
            contributions.append({
                "component": name,
                "raw_score": raw,
                "weight": weight,
                "weighted_contribution": contribution,
                "max_contribution": max_contribution,
                "gap_to_max": gap_to_max,
            })

        blockers = sorted(contributions, key=lambda x: x["gap_to_max"], reverse=True)[:3]

        return {
            "symbol": r.get("symbol"),
            "option_type": option_type,
            "directional_bias": r.get("directional_bias"),
            "result": r.get("result"),
            "composite_score": score,
            "distance_to_execute": distance,
            "direction_confidence": r.get("direction_confidence"),
            "top_blockers": blockers,
            "contributions": contributions,
        }

    def _num(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
