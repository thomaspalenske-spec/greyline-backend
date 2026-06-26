class DynamicDivestmentEngine:
    """
    Simulator-side dynamic divestment engine.

    Purpose:
      Replace arbitrary fixed 25% TP harvests with environment-aware
      divestment recommendations.

    Rule:
      Simulator adapts to GreyLine OS.
      Production/live engines are not modified here.

    Output:
      divestment_pct = percentage of original position to sell at this TP event.
    """

    def evaluate(
        self,
        tp_stage,
        signal,
        ret_pct,
        high_water_return,
        remaining_position,
        market_context=None,
    ):
        signal = signal or {}
        market_context = market_context or {}

        score = float(signal.get("composite_score") or signal.get("score") or 0)
        risk = float(signal.get("risk_state_score") or 50)
        regime = float(signal.get("regime_score") or 50)
        confidence = float(signal.get("direction_confidence") or 0)

        max_favorable = float(high_water_return or ret_pct or 0)
        giveback = max(0.0, max_favorable - float(ret_pct or 0))

        # Baseline by TP stage.
        base = {
            "TP1": 0.18,
            "TP2": 0.22,
            "TP3": 0.28,
        }.get(str(tp_stage).upper(), 0.25)

        # Strong environment = harvest less, keep more runner exposure.
        if score >= 90:
            base -= 0.06
        elif score < 86:
            base += 0.06

        if regime >= 85:
            base -= 0.05
        elif regime < 60:
            base += 0.10

        if risk >= 80:
            base -= 0.04
        elif risk < 65:
            base += 0.12

        if confidence >= 25:
            base -= 0.03
        elif confidence < 8:
            base += 0.08

        # If trade has started giving back gains, harvest more.
        if giveback >= 5:
            base += 0.15
        elif giveback >= 3:
            base += 0.08

        # Later TP stages should protect more profit unless environment is excellent.
        if str(tp_stage).upper() == "TP3" and not (score >= 90 and regime >= 85 and risk >= 75):
            base += 0.08

        divestment_pct = min(max(base, 0.05), remaining_position)

        return {
            "tp_stage": tp_stage,
            "divestment_pct": round(divestment_pct, 4),
            "divestment_pct_display": round(divestment_pct * 100, 2),
            "remaining_position_before": round(remaining_position, 4),
            "remaining_position_after": round(max(0.0, remaining_position - divestment_pct), 4),
            "score": score,
            "risk_state_score": risk,
            "regime_score": regime,
            "direction_confidence": confidence,
            "ret_pct": round(float(ret_pct or 0), 2),
            "high_water_return": round(float(high_water_return or 0), 2),
            "giveback_pct": round(giveback, 2),
            "status": "DYNAMIC_DIVESTMENT_READY",
        }
