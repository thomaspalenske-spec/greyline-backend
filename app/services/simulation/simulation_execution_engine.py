from app.services.options_entry_quality_gate_engine import OptionsEntryQualityGateEngine


class SimulationExecutionEngine:
    """
    First-pass simulated execution engine.

    Current behavior:
    - EXECUTE opens a synthetic equity position using current replay close.
    - WATCH / OBSERVE do not deploy capital.
    - No future data is used.
    """

    def evaluate(self, decision_row, capital):
        decision_row = decision_row or {}
        candidate = decision_row.get("candidate") or {}
        market_data = decision_row.get("market_data") or {}
        decision = decision_row.get("decision")

        close = self._num(market_data.get("close"))
        capital = float(capital or 0)

        if decision != "EXECUTE" or close is None:
            return {
                "action": "NO_FILL",
                "capital_before": capital,
                "capital_after": capital,
                "position_opened": False,
                "reason": "NO_EXECUTE_SIGNAL_OR_NO_PRICE",
                "future_data_used": False,
                "status": "SIMULATION_EXECUTION_READY",
            }

        simulated_dte = self._num(candidate.get("initial_contract_days"))
        if simulated_dte is None:
            simulated_dte = self._num(candidate.get("remaining_contract_days"))
        if simulated_dte is None:
            simulated_dte = 30

        simulated_entry_price = max(close * 0.01, 0.01)
        candidate_score = (
            candidate.get("candidate_score")
            or candidate.get("adjusted_score")
            or candidate.get("composite_score")
            or 0
        )

        entry_quality_gate = OptionsEntryQualityGateEngine().evaluate(
            candidate_score=candidate_score,
            initial_contract_days=simulated_dte,
            entry_price=simulated_entry_price,
        )

        if entry_quality_gate.get("approved") is not True:
            return {
                "action": "NO_FILL",
                "capital_before": capital,
                "capital_after": capital,
                "position_opened": False,
                "reason": "SIMULATION_OPTIONS_ENTRY_QUALITY_GATE_BLOCK",
                "entry_quality_gate": entry_quality_gate,
                "future_data_used": False,
                "status": "SIMULATION_EXECUTION_ENTRY_QUALITY_BLOCKED",
            }

        allocation_pct = 0.10
        deployed = round(capital * allocation_pct, 2)
        shares = round(deployed / close, 6) if close else 0

        return {
            "action": "BUY_TO_OPEN",
            "symbol": decision_row.get("symbol"),
            "direction": candidate.get("directional_bias"),
            "option_type": candidate.get("option_type"),
            "composite_score": candidate.get("composite_score"),
            "regime": candidate.get("regime"),
            "regime_score": candidate.get("regime_score"),
            "risk_state": candidate.get("risk_state"),
            "risk_state_score": candidate.get("risk_state_score"),
            "institutional_sponsorship_score": candidate.get("institutional_sponsorship_score"),
            "institutional_inflow_score": candidate.get("institutional_inflow_score"),
            "institutional_outflow_score": candidate.get("institutional_outflow_score"),
            "net_institutional_flow_score": candidate.get("net_institutional_flow_score"),
            "institutional_flow_direction": candidate.get("institutional_flow_direction"),
            "institutional_flow_confidence": candidate.get("institutional_flow_confidence"),
            "institutional_flow_reasons": candidate.get("institutional_flow_reasons"),
            "footprint_confirmed_sponsorship": candidate.get("footprint_confirmed_sponsorship"),
            "trend_persistence_score": candidate.get("trend_persistence_score"),
            "breadth_score": candidate.get("breadth_score"),
            "asymmetry_score": candidate.get("asymmetry_score"),
            "volatility_score": candidate.get("volatility_score"),
            "expected_value_score": candidate.get("expected_value_score"),
            "direction_confidence": candidate.get("direction_confidence"),
            "historical_execution_bonus": candidate.get("historical_execution_bonus"),
            "bullish_score": candidate.get("bullish_score"),
            "bearish_score": candidate.get("bearish_score"),
            "setup_score": candidate.get("setup_score"),
            "entry_time": market_data.get("timestamp"),
            "entry_price": close,
            "entry_quality_gate": entry_quality_gate,
            "simulated_option_entry_price": simulated_entry_price,
            "simulated_contract_days": simulated_dte,
            "shares": shares,
            "capital_deployed": deployed,
            "capital_before": capital,
            "capital_after": round(capital - deployed, 2),
            "position_opened": True,
            "future_data_used": False,
            "status": "SIMULATION_EXECUTION_READY",
        }

    @staticmethod
    def _num(value):
        try:
            return float(value) if value not in [None, ""] else None
        except Exception:
            return None
