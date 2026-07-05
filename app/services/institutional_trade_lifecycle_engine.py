from datetime import datetime


class InstitutionalTradeLifecycleEngine:
    def evaluate(self, candidate: dict):
        flow = candidate.get("institutional_flow_direction")
        consensus = float(candidate.get("institutional_flow_consensus_score") or 0)
        momentum = float(candidate.get("institutional_flow_momentum_score") or 0)
        decay = candidate.get("institutional_flow_decay") is True
        result = candidate.get("result")

        phase = "ENTRY"
        action = "HOLD"
        scale = 1.0
        stop = "UNCHANGED"

        if result == "EXECUTE":
            action = "ENTER"

        if flow == "INFLOW" and consensus >= 90 and momentum >= 75 and not decay:
            phase = "ACCUMULATION"
            action = "ADD_25_PCT"
            scale = 1.25
            stop = "TIGHTEN"

        elif flow == "INFLOW" and momentum >= 90:
            phase = "EXPANSION"
            action = "TRAIL_STOP"

        elif decay:
            phase = "DISTRIBUTION"
            action = "REDUCE_25_PCT"

        elif flow == "OUTFLOW":
            phase = "EXIT"
            action = "EXIT"

        return {
            "trade_phase": phase,
            "trade_action": action,
            "position_multiplier": scale,
            "stop_adjustment": stop,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "TRADE_LIFECYCLE_READY",
        }
