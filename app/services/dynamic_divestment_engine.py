from datetime import datetime


class DynamicDivestmentEngine:
    """
    GreyLine OS dynamic divestment advisor.

    Replaces arbitrary fixed 25% TP harvest assumptions with environment-aware
    recommended divestment percentages.

    Safety:
      Reporting/advisory only.
      Does not place orders.
      Does not enable live partial exits.
    """

    def evaluate(self, trade, tp_stage):
        trade = trade or {}

        score = float(
            trade.get("composite_score")
            or trade.get("score")
            or trade.get("candidate_score")
            or 0
        )
        risk = float(trade.get("risk_state_score") or trade.get("risk_score") or 50)
        regime = float(trade.get("regime_score") or 50)
        confidence = float(trade.get("direction_confidence") or trade.get("confidence_score") or 0)
        volatility = float(trade.get("volatility_score") or 50)
        unrealized_pct = float(trade.get("unrealized_pnl_pct") or trade.get("return_pct") or 0)
        high_water = float(trade.get("max_favorable_pct") or unrealized_pct or 0)
        giveback = max(0.0, high_water - unrealized_pct)

        qty = float(
            trade.get("quantity")
            or trade.get("contracts")
            or trade.get("original_position_size")
            or 0
        )

        remaining = float(
            trade.get("position_remaining_after_tp_exits")
            or trade.get("remaining_position")
            or qty
            or 0
        )

        base = {
            "TP1": 0.18,
            "TP2": 0.22,
            "TP3": 0.28,
        }.get(str(tp_stage).upper(), 0.25)

        if score >= 90:
            base -= 0.06
        elif score and score < 86:
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
        elif confidence and confidence < 8:
            base += 0.08

        if volatility >= 80:
            base += 0.05

        if giveback >= 5:
            base += 0.15
        elif giveback >= 3:
            base += 0.08

        if str(tp_stage).upper() == "TP3" and not (score >= 90 and regime >= 85 and risk >= 75):
            base += 0.08

        divestment_fraction = min(max(base, 0.05), 1.0)
        recommended_qty = round(qty * divestment_fraction, 4) if qty else None

        if remaining and recommended_qty is not None:
            recommended_qty = min(recommended_qty, remaining)

        return {
            "dynamic_divestment_engine": "ACTIVE",
            "dynamic_divestment_last_calculated_at": datetime.utcnow().isoformat(),
            "tp_stage": tp_stage,
            "recommended_divestment_pct": round(divestment_fraction * 100, 2),
            "recommended_exit_qty": recommended_qty,
            "remaining_position_before": remaining,
            "score": score,
            "risk_state_score": risk,
            "regime_score": regime,
            "direction_confidence": confidence,
            "volatility_score": volatility,
            "unrealized_pnl_pct": unrealized_pct,
            "high_water_return_pct": high_water,
            "giveback_pct": round(giveback, 2),
            "dynamic_divestment_execution_enabled": False,
            "dynamic_divestment_reporting_only": True,
            "status": "DYNAMIC_DIVESTMENT_ADVISORY_READY",
        }
