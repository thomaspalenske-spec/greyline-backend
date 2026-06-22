from datetime import datetime


class DynamicTPManagementEngine:
    """
    Reporting-only adaptive TP engine.
    Does not execute orders.
    Recalculates TP2, TP3, and runner logic from current trade environment.
    TP1 remains fixed for risk reduction.
    """

    def evaluate(self, trade):
        entry = float(trade.get("entry_price") or 0)
        current = float(trade.get("current_price") or 0)

        if entry <= 0:
            return {
                "dynamic_tp_engine": "UNAVAILABLE",
                "dynamic_tp_status": "MISSING_ENTRY_PRICE",
            }

        asset_type = str(trade.get("asset_type") or trade.get("contract_type") or "").upper()

        volatility_score = float(trade.get("volatility_score") or 50)
        unrealized_pct = float(trade.get("unrealized_pnl_pct") or 0)

        # Existing TP1 stays fixed. TP2/TP3/TP4 become adaptive.
        if asset_type == "OPTION":
            base_tp1 = 0.25
            base_tp2 = 0.50
            base_tp3 = 0.75
        else:
            base_tp = float(trade.get("take_profit_pct") or 8.0) / 100
            base_tp1 = base_tp * 0.25
            base_tp2 = base_tp * 0.50
            base_tp3 = base_tp * 0.75

        # Environment adjustment factor.
        # Stronger/profitable environment stretches TP2/TP3.
        # Weaker/loss-making environment pulls targets closer.
        adjustment = 1.0

        if volatility_score >= 80:
            adjustment -= 0.10
        elif volatility_score <= 40:
            adjustment += 0.10

        if unrealized_pct >= 5:
            adjustment += 0.15
        elif unrealized_pct <= -3:
            adjustment -= 0.15

        adjustment = max(0.70, min(1.35, adjustment))

        dynamic_tp1_price = round(entry * (1 + base_tp1), 2)
        dynamic_tp2_price = round(entry * (1 + (base_tp2 * adjustment)), 2)
        dynamic_tp3_price = round(entry * (1 + (base_tp3 * adjustment)), 2)

        runner_active = bool(
            current >= dynamic_tp3_price and current > 0
        )

        if runner_active:
            position_stage = "RUNNER_ACTIVE"
            tp4_mode = "DYNAMIC_RUNNER_TRAILING_EXIT"
        elif current >= dynamic_tp2_price and current > 0:
            position_stage = "TP3_PENDING"
            tp4_mode = "NOT_ACTIVE"
        elif current >= dynamic_tp1_price and current > 0:
            position_stage = "TP2_PENDING"
            tp4_mode = "NOT_ACTIVE"
        else:
            position_stage = "TP1_PENDING"
            tp4_mode = "NOT_ACTIVE"

        if current:
            dynamic_tp2_distance_dollars = round(dynamic_tp2_price - current, 2)
            dynamic_tp2_distance_pct = round(((dynamic_tp2_price - current) / current) * 100, 2)
            dynamic_tp3_distance_dollars = round(dynamic_tp3_price - current, 2)
            dynamic_tp3_distance_pct = round(((dynamic_tp3_price - current) / current) * 100, 2)
        else:
            dynamic_tp2_distance_dollars = None
            dynamic_tp2_distance_pct = None
            dynamic_tp3_distance_dollars = None
            dynamic_tp3_distance_pct = None

        return {
            "dynamic_tp_engine": "ACTIVE",
            "dynamic_tp_last_calculated_at": datetime.utcnow().isoformat(),
            "position_stage": position_stage,

            "tp1_policy": "FIXED_RISK_REDUCTION",
            "dynamic_tp1_price": dynamic_tp1_price,

            "tp2_policy": "ADAPTIVE_ENVIRONMENT_RECALCULATED",
            "dynamic_tp2_price": dynamic_tp2_price,
            "dynamic_tp2_distance_dollars": dynamic_tp2_distance_dollars,
            "dynamic_tp2_distance_pct": dynamic_tp2_distance_pct,

            "tp3_policy": "ADAPTIVE_TREND_EXTENSION",
            "dynamic_tp3_price": dynamic_tp3_price,
            "dynamic_tp3_distance_dollars": dynamic_tp3_distance_dollars,
            "dynamic_tp3_distance_pct": dynamic_tp3_distance_pct,

            "tp4_policy": "DYNAMIC_RUNNER_NO_FIXED_TARGET",
            "tp4_mode": tp4_mode,
            "runner_active": runner_active,

            "dynamic_tp_adjustment_factor": round(adjustment, 2),
            "dynamic_tp_adjustment_reason": self._reason(volatility_score, unrealized_pct),
            "dynamic_tp_execution_enabled": False,
            "dynamic_tp_reporting_only": True,
        }

    def _reason(self, volatility_score, unrealized_pct):
        reasons = []

        if volatility_score >= 80:
            reasons.append("HIGH_VOLATILITY_PULL_TARGETS_CLOSER")
        elif volatility_score <= 40:
            reasons.append("LOW_VOLATILITY_ALLOW_TARGET_EXTENSION")
        else:
            reasons.append("NORMAL_VOLATILITY")

        if unrealized_pct >= 5:
            reasons.append("TRADE_WORKING_EXTEND_TARGETS")
        elif unrealized_pct <= -3:
            reasons.append("TRADE_UNDER_PRESSURE_PULL_TARGETS_CLOSER")
        else:
            reasons.append("P_AND_L_NEUTRAL")

        return reasons
