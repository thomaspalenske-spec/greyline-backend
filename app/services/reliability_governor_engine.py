from datetime import datetime
from pathlib import Path
import json

from app.services.operator_event_bus_engine import OperatorEventBusEngine

import requests


class ReliabilityGovernorEngine:
    """
    Reliability authority gate.

    Converts reliability status into operational authority.
    Does not place trades, cancel orders, or restart services.
    """

    def evaluate(self, simulate_fault=None):
        system_health = requests.get("http://127.0.0.1:8000/system-health-snapshot", timeout=5).json()
        scheduler = requests.get("http://127.0.0.1:8000/background-scheduler/status", timeout=5).json()
        quote = requests.get("http://127.0.0.1:8000/fast-quote-heartbeat/status", timeout=5).json()
        token = requests.get("http://127.0.0.1:8000/tradestation-token-status", timeout=5).json()

        checks = {
            "system_health_ok": system_health.get("overall_health") == "GREEN",
            "scheduler_ok": bool(scheduler.get("scheduler_enabled")) and bool(scheduler.get("thread_alive")),
            "quote_ok": quote.get("status") == "FAST_QUOTE_HEARTBEAT_STATUS_READY",
            "token_ok": bool(token.get("ready_for_read_only")),
        }

        score = 25 * sum(1 for v in checks.values() if v)
        critical_actions = []

        if not checks["system_health_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "system health not green"})
        if not checks["scheduler_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "scheduler not running"})
        if not checks["quote_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "quote heartbeat not ready"})
        if not checks["token_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "TradeStation token not ready"})

        reliability = "GREEN" if score == 100 else ("YELLOW" if score >= 75 else "RED")
        posture = "OPERATIONAL" if reliability == "GREEN" else "OPERATOR_ACTION_REQUIRED"
        actions = critical_actions

        if reliability == "GREEN" and score >= 95:
            mode = "PAPER_OPERATIONAL"
            execution_allowed = True
            new_entries_allowed = True
            autonomous_allowed = False
            reason = "Reliability checks healthy; paper execution allowed. Live autonomous execution remains disabled."

        elif reliability == "YELLOW" and score >= 85:
            mode = "RECOMMEND_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Reliability degraded. Recommendations allowed; execution blocked."

        elif critical_actions or reliability == "RED":
            mode = "SAFE_MODE"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Critical reliability issue detected. Execution blocked."

        else:
            mode = "OBSERVE_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Reliability below operational threshold."


        severity = {
            "PAPER_OPERATIONAL": "INFO",
            "RECOMMEND_ONLY": "WARNING",
            "OBSERVE_ONLY": "WARNING",
            "SAFE_MODE": "CRITICAL",
        }.get(mode, "INFO")

        ack_required = mode in ["OBSERVE_ONLY", "HALT"]

        state_file = Path("app/data/operator_events/reliability_governor_state.json")
        state_file.parent.mkdir(parents=True, exist_ok=True)

        previous_mode = None
        if state_file.exists():
            try:
                previous_mode = (json.loads(state_file.read_text()) or {}).get("operating_mode")
            except Exception:
                previous_mode = None

        mode_changed = previous_mode != mode

        if mode_changed:
            OperatorEventBusEngine().publish(
                source="ReliabilityGovernorEngine",
                category="OPERATING_MODE",
                severity=severity,
                title=f"Reliability Mode: {mode}",
                message=f"GreyLine reliability governor entered {mode}.",
                symbol=None,
                trade_id=None,
                ack_required=ack_required,
                payload={
                    "previous_operating_mode": previous_mode,
                    "operating_mode": mode,
                    "reliability_score": score,
                    "execution_allowed": execution_allowed,
                    "new_entries_allowed": new_entries_allowed,
                    "autonomous_allowed": autonomous_allowed,
                },
            )

        state_file.write_text(json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "operating_mode": mode,
            "reliability_score": score,
            "overall_reliability": reliability,
            "execution_allowed": execution_allowed,
            "new_entries_allowed": new_entries_allowed,
            "autonomous_allowed": autonomous_allowed,
        }, indent=2))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "RELIABILITY_GOVERNOR",
            "operating_mode": mode,
            "execution_allowed": execution_allowed,
            "new_entries_allowed": new_entries_allowed,
            "autonomous_allowed": autonomous_allowed,
            "reason": reason,
            "overall_reliability": reliability,
            "reliability_score": score,
            "posture": posture,
            "critical_action_count": len(critical_actions),
            "actions": actions,
            "simulate_fault": simulate_fault,
            "status": "RELIABILITY_GOVERNOR_READY",
        }
