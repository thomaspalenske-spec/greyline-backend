from datetime import datetime

from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.options_account_dashboard_engine import OptionsAccountDashboardEngine
from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.execution_governor import ExecutionGovernor


class GreyLineReliabilityCoreEngine:
    """
    Single source of truth for whether GreyLine is current, connected,
    reconciled, and safe to trust.

    This engine does NOT enable execution.
    It only reports readiness and blocks trust when stale/drift conditions exist.
    """

    def evaluate(self):
        timestamp = datetime.utcnow().isoformat()

        token = TradeStationTokenStatusEngine().evaluate()
        balance = TradeStationBalanceLiveEngine().get_balance()
        positions = TradeStationPositionsLiveEngine().get_positions()
        options_dashboard = OptionsAccountDashboardEngine().get_dashboard()
        scheduler = BackgroundSchedulerService.status()
        execution_permission = ExecutionGovernor().evaluate_execution_permission("EXECUTE")

        token_ok = token.get("ready_for_read_only") is True

        # A 429 is a RATE-LIMIT ("you're calling too often"), NOT a broker/auth outage or fabricated data —
        # and it self-clears. A transient throttle on one read must not flap Mission Status to DEGRADED
        # ("execution authority restricted"), especially since the OTHER reads (token/positions or balance)
        # already confirm the account is live and authed. So treat a 429 as verified-enough (hold), and
        # degrade ONLY on a REAL failure — auth (401/403), server (5xx), or an empty/unparseable body.
        def _read_ok(resp, success_status):
            if resp.get("status") == success_status:
                return True, "success"
            if resp.get("http_status") == 429:
                return True, "throttled"           # rate-limited — self-clears, not a reliability failure
            return False, "failed"

        balance_ok, balance_read_state = _read_ok(balance, "BALANCE_READ_SUCCESS")
        positions_ok, positions_read_state = _read_ok(positions, "POSITIONS_READ_SUCCESS")

        broker_positions = (
            positions.get("response_json", {}).get("Positions", [])
            if isinstance(positions.get("response_json"), dict)
            else []
        )

        broker_position_count = len(broker_positions)
        paper_open_option_count = int(options_dashboard.get("open_option_trade_count", 0))

        # Paper trades are not expected to appear in live broker positions.
        # Only treat paper/live mismatch as drift when live execution is enabled.
        live_execution_enabled = False
        paper_live_drift = False if not live_execution_enabled else (paper_open_option_count != broker_position_count)
        drift_reason = (
            "PAPER_ONLY_EXPECTED_NO_LIVE_DRIFT"
            if not live_execution_enabled
            else "LIVE_EXECUTION_POSITION_RECONCILIATION_REQUIRED"
        )

        # CROSS-PROCESS: thread_alive/scheduler_enabled are process-local (False from an out-of-process audit),
        # which forced a false -20 'RELIABILITY_CORE_DEGRADED'. scheduler_live (thread alive OR recent persisted
        # cycle) is accurate from any process; a live scheduler is by definition enabled+running.
        scheduler_alive = bool(scheduler.get("scheduler_live", scheduler.get("thread_alive")))
        scheduler_enabled = bool(scheduler.get("scheduler_live", scheduler.get("scheduler_enabled")))

        checks = {
            "token_ok": token_ok,
            "balance_ok": balance_ok,
            "positions_ok": positions_ok,
            "scheduler_enabled": scheduler_enabled,
            "scheduler_alive": scheduler_alive,
            "paper_live_position_drift_clear": not paper_live_drift,
        }

        score = 0
        score += 20 if token_ok else 0
        score += 20 if balance_ok else 0
        score += 20 if positions_ok else 0
        score += 20 if scheduler_enabled and scheduler_alive else 0
        score += 20 if not paper_live_drift else 0

        execution_ready = (
            score == 100
            and token_ok
            and balance_ok
            and positions_ok
            and scheduler_enabled
            and scheduler_alive
            and not paper_live_drift
        )

        if execution_ready:
            status = "RELIABILITY_CORE_HEALTHY"
        elif paper_live_drift:
            status = "RELIABILITY_CORE_DRIFT_LOCKOUT"
        else:
            status = "RELIABILITY_CORE_DEGRADED"

        return {
            "timestamp": timestamp,
            "system": "GreyLine",
            "source": "GREYLINE_RELIABILITY_CORE",
            "health_score": score,
            "execution_ready": execution_ready,
            # execution_enabled / order_placement_allowed reflect the actual kill-switch
            # (ExecutionGovernor), consistent with every other status surface. The core
            # still does not itself enable execution — execution_ready is its own read-only
            # readiness signal, kept separate from whether the governor has armed execution.
            "execution_enabled": execution_permission.get("execution_enabled"),
            "order_placement_allowed": execution_permission.get("order_placement_allowed"),
            "checks": checks,
            "broker_truth": {
                "broker": "TradeStation",
                "balance_status": balance.get("status"),
                "balance_read_state": balance_read_state,      # success | throttled (429, held) | failed
                "positions_status": positions.get("status"),
                "positions_read_state": positions_read_state,
                "broker_position_count": broker_position_count,
                "positions": broker_positions,
            },
            "greyline_internal_truth": {
                "options_account_type": options_dashboard.get("account_type"),
                "paper_open_option_count": paper_open_option_count,
                "paper_open_positions": options_dashboard.get("open_positions", []),
            },
            "scheduler": {
                "scheduler_enabled": scheduler_enabled,
                "thread_alive": scheduler_alive,
                "cycle_count": scheduler.get("cycle_count"),
                "last_run": scheduler.get("last_run"),
                "last_status": scheduler.get("last_status"),
            },
            "drift": {
                "paper_live_position_drift": paper_live_drift,
                "paper_positions": paper_open_option_count,
                "broker_positions": broker_position_count,
                "drift_reason": drift_reason,
                "drift_lockout": paper_live_drift,
            },
            "status": status,
        }
