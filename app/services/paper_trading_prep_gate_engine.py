from datetime import datetime


class PaperTradingPrepGateEngine:

    def evaluate_prep_gate(
        self,
        backend_ready,
        broker_safety_ready,
        credential_safety_ready,
        authority_gate_ready,
        kill_switch_ready
    ):

        prep_gate_passed = (
            backend_ready
            and broker_safety_ready
            and credential_safety_ready
            and authority_gate_ready
            and kill_switch_ready
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "backend_ready": backend_ready,
            "broker_safety_ready": broker_safety_ready,
            "credential_safety_ready": credential_safety_ready,
            "authority_gate_ready": authority_gate_ready,
            "kill_switch_ready": kill_switch_ready,
            "prep_gate_passed": prep_gate_passed,
            "next_mode": "PAPER_TRADING_PREP" if prep_gate_passed else "LOCAL_DEVELOPMENT"
        }
