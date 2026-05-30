from datetime import datetime


class BackendPhaseGateEngine:

    def evaluate_phase_gate(
        self,
        backend_ready,
        control_center_online,
        ucf_registry_active,
        capability_registry_active,
        milestone_registry_active
    ):

        phase_gate_passed = (
            backend_ready
            and control_center_online
            and ucf_registry_active
            and capability_registry_active
            and milestone_registry_active
        )

        next_phase = "BROKER_API_PREP" if phase_gate_passed else "FOUNDATION_BUILD"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "backend_ready": backend_ready,
            "control_center_online": control_center_online,
            "ucf_registry_active": ucf_registry_active,
            "capability_registry_active": capability_registry_active,
            "milestone_registry_active": milestone_registry_active,
            "phase_gate_passed": phase_gate_passed,
            "next_phase": next_phase
        }
