from datetime import datetime
from pathlib import Path
import json

from app.services.operator_event_bus_engine import OperatorEventBusEngine



class ReliabilityGovernorEngine:
    """
    Reliability authority gate.

    Converts reliability status into operational authority.
    Does not place trades, cancel orders, or restart services.
    """

    STATE_FILE = Path("app/data/operator_events/reliability_governor_state.json")

    def evaluate(self, simulate_fault=None):
        from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
        from app.services.background_scheduler_service import BackgroundSchedulerService
        from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService
        from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine

        system_health = SystemHealthDashboardEngine().status()
        scheduler = BackgroundSchedulerService.status()
        quote = FastQuoteHeartbeatService.status()
        token = TradeStationTokenStatusEngine().evaluate()

        checks_list = system_health.get("checks") or []
        red_count = int(system_health.get("red_count") or 0)
        red_count = red_count or sum(1 for c in checks_list if c.get("status") == "RED")
        health_value = system_health.get("overall_health") or system_health.get("status")
        system_health_ok = (
            health_value in ("GREEN", "YELLOW", "HEALTHY", "SYSTEM_HEALTH_READY")
            and red_count == 0
        )

        checks = {
            "system_health_ok": system_health_ok,
            # CROSS-PROCESS liveness — scheduler_live is (thread alive OR recent persisted cycle), so this
            # governor never falsely fires "scheduler not running" when evaluated outside the service process.
            "scheduler_ok": bool(scheduler.get(
                "scheduler_live",
                bool(scheduler.get("thread_alive"))
                or scheduler.get("last_status") == "BACKGROUND_SCHEDULER_CYCLE_COMPLETE")),
            "quote_ok": quote.get("status") == "FAST_QUOTE_HEARTBEAT_STATUS_READY",
            "token_ok": bool(token.get("ready_for_read_only")),
        }

        score = 25 * sum(1 for v in checks.values() if v)
        critical_actions = []

        if not checks["system_health_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "system health has red checks"})
        if not checks["scheduler_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "scheduler not running"})
        if not checks["quote_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "quote heartbeat not ready"})
        if not checks["token_ok"]:
            critical_actions.append({"severity": "CRITICAL", "problem": "TradeStation token not ready"})

        reliability = "GREEN" if score == 100 else ("YELLOW" if score >= 75 else "RED")
        posture = "OPERATIONAL" if reliability == "GREEN" else "OPERATOR_ACTION_REQUIRED"
        actions = critical_actions

        # DEBOUNCE the broker-side TRANSIENT checks (quote heartbeat, TS token) so a single blip — the
        # exact benign condition a saturated scheduler cycle produces — does NOT flip GREEN->SAFE_MODE and
        # page CRITICAL. A single/short transient (with the STRUCTURAL checks healthy) is RECOMMEND_ONLY
        # (WARNING); it escalates to SAFE_MODE only once it PERSISTS. Structural failures (system health,
        # scheduler) and any multi-check RED still enter SAFE_MODE immediately. Execution stays BLOCKED in
        # every degraded mode either way — this only changes the alarm severity/label, never loosens exec.
        from os import getenv as _getenv
        try:
            _streak_threshold = max(1, int(_getenv("GREYLINE_RELIABILITY_TRANSIENT_STREAK", "") or 3))
        except (TypeError, ValueError):
            _streak_threshold = 3
        structural_fail = (not checks["system_health_ok"]) or (not checks["scheduler_ok"])
        transient_fail = (not checks["quote_ok"]) or (not checks["token_ok"])

        state_file = self.STATE_FILE
        state_file.parent.mkdir(parents=True, exist_ok=True)
        previous_mode, prev_streak = None, 0
        if state_file.exists():
            try:
                _prev = json.loads(state_file.read_text()) or {}
                previous_mode = _prev.get("operating_mode")
                prev_streak = int(_prev.get("transient_fail_streak") or 0)
            except Exception:
                previous_mode, prev_streak = None, 0
        transient_streak = (prev_streak + 1) if transient_fail else 0

        if reliability == "GREEN" and score >= 95:
            mode = "PAPER_OPERATIONAL"
            execution_allowed = True
            new_entries_allowed = True
            autonomous_allowed = False
            reason = "Reliability checks healthy; paper execution allowed. Live autonomous execution remains disabled."

        elif structural_fail or reliability == "RED" or (transient_fail and transient_streak >= _streak_threshold):
            mode = "SAFE_MODE"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Critical reliability issue detected. Execution blocked."

        elif transient_fail:
            # broker-side read (quote/token) unverified but STRUCTURE healthy and not yet persistent:
            # recommendations only, execution blocked — no CRITICAL page for a self-healing blip.
            mode = "RECOMMEND_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = (f"Transient broker read unverified ({transient_streak}/{_streak_threshold} cycles); "
                      f"recommendations only, execution blocked. Escalates to SAFE_MODE if it persists.")

        elif reliability == "YELLOW" and score >= 85:
            mode = "RECOMMEND_ONLY"
            execution_allowed = False
            new_entries_allowed = False
            autonomous_allowed = False
            reason = "Reliability degraded. Recommendations allowed; execution blocked."

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

        # previous_mode + prev_streak were already read above (needed for the debounce decision).
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
            "transient_fail_streak": transient_streak,
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
            "transient_fail_streak": transient_streak,
            "actions": actions,
            "simulate_fault": simulate_fault,
            "status": "RELIABILITY_GOVERNOR_READY",
        }
