from datetime import datetime


class GovernanceHealthEngine:

    def calculate_health(
        self,
        integrity_pass,
        reconciliation_status,
        lifecycle_valid,
        drift_detected,
        snapshot_valid
    ):
        score = 100
        reasons = []

        if integrity_pass is not True:
            score -= 25
            reasons.append("INTEGRITY_CONTROL_FAILED")

        if reconciliation_status != "PASS":
            score -= 20
            reasons.append("POSITION_RECONCILIATION_FAILED")

        if lifecycle_valid is not True:
            score -= 20
            reasons.append("POSITION_LIFECYCLE_INVALID")

        if drift_detected:
            score -= 20
            reasons.append("ACCOUNT_DRIFT_DETECTED")

        if snapshot_valid is not True:
            score -= 15
            reasons.append("SNAPSHOT_INVALID")

        score = max(score, 0)

        if score >= 90:
            health_level = "GREEN"
        elif score >= 70:
            health_level = "YELLOW"
        else:
            health_level = "RED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health_score": score,
            "health_level": health_level,
            "reasons": reasons,
            "execution_allowed": False,
            "order_placement_allowed": False,
            "status": "GOVERNANCE_HEALTHY" if health_level == "GREEN" else "GOVERNANCE_DEGRADED"
        }
