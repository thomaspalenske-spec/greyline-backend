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
            "entry_price": close,
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
