import threading
import time
from datetime import datetime
from os import getenv
from app.services.execution_governor import ExecutionGovernor
from pathlib import Path

from app.services.persistence.json_store import atomic_write_json, read_json

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.decision_scheduler_engine import DecisionSchedulerEngine
from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine
from app.services.decision_learning_memory_engine import DecisionLearningMemoryEngine
from app.services.fixed_horizon_grader_engine import FixedHorizonGraderEngine
from app.services.persistence.json_store import append_jsonl
from app.services.paper_position_manager_engine import PaperPositionManagerEngine
from app.services.options_position_manager_engine import OptionsPositionManagerEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine
from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine
from app.services.market_hours_engine import MarketHoursEngine
from app.services.forecast_outcome_grader_engine import ForecastOutcomeGraderEngine
from app.services.institutional.institutional_signal_snapshot_sweep_engine import (
    InstitutionalSignalSnapshotSweepEngine,
)
from app.services.institutional.institutional_retraining_orchestrator_engine import (
    InstitutionalRetrainingOrchestratorEngine,
)


class BackgroundSchedulerService:
    _state_file = Path("app/data/runtime/background_scheduler_state.json")
    _thread = None
    _stop_event = threading.Event()
    _enabled = False
    _last_run = None
    _last_status = None
    _cycle_count = 0
    # Cycle-health observability (previously only last_status was tracked, so
    # transient/flapping failures were invisible).
    _success_count = 0
    _failure_count = 0
    _consecutive_failures = 0
    _last_error = None
    _last_error_at = None
    _last_duration_ms = None
    _recent_cycles = []
    _RECENT_CAP = 20

    @classmethod
    def _record_result(cls, status, started, error=None):
        try:
            start_dt = datetime.fromisoformat(started) if isinstance(started, str) else started
            duration_ms = int((datetime.utcnow() - start_dt).total_seconds() * 1000)
        except Exception:
            duration_ms = None

        cls._last_duration_ms = duration_ms
        if status == "COMPLETE":
            cls._success_count += 1
            cls._consecutive_failures = 0
        else:
            cls._failure_count += 1
            cls._consecutive_failures += 1
            cls._last_error = error
            cls._last_error_at = datetime.utcnow().isoformat()

        entry = {"status": status, "at": datetime.utcnow().isoformat(), "duration_ms": duration_ms, "error": error}
        cls._recent_cycles = (cls._recent_cycles + [entry])[-cls._RECENT_CAP:]

        # Durable per-cycle heartbeat. recent_cycles is capped in memory/state, so it
        # can't reveal multi-day gaps. This append-only beat lets ContinuityMonitorEngine
        # detect when accumulation actually stopped — a laptop sleep, a reboot, a crash —
        # so a gap in the data can't masquerade as "nothing happened".
        try:
            append_jsonl(Path("app/data/continuity/heartbeat.jsonl"),
                         {"at": entry["at"], "status": status})
        except Exception:
            pass

    @classmethod
    def _load_state(cls):
        data = read_json(cls._state_file, default=dict) or {}
        try:
            cls._last_run = data.get("last_run")
            cls._last_status = data.get("last_status")
            cls._cycle_count = int(data.get("cycle_count", 0) or 0)
            cls._success_count = int(data.get("success_count", 0) or 0)
            cls._failure_count = int(data.get("failure_count", 0) or 0)
            cls._consecutive_failures = int(data.get("consecutive_failures", 0) or 0)
            cls._last_error = data.get("last_error")
            cls._last_error_at = data.get("last_error_at")
            cls._recent_cycles = data.get("recent_cycles", []) or []
        except (AttributeError, ValueError, TypeError):
            pass

    @classmethod
    def _save_state(cls):
        atomic_write_json(cls._state_file, {
            "last_run": cls._last_run,
            "last_status": cls._last_status,
            "cycle_count": cls._cycle_count,
            "success_count": cls._success_count,
            "failure_count": cls._failure_count,
            "consecutive_failures": cls._consecutive_failures,
            "last_error": cls._last_error,
            "last_error_at": cls._last_error_at,
            "recent_cycles": cls._recent_cycles,
        })

    @classmethod
    def start(cls, interval_seconds=300):
        if cls._enabled:
            return cls.status()

        cls._enabled = True
        cls._stop_event.clear()

        cls._thread = threading.Thread(
            target=cls._run_loop,
            args=(interval_seconds,),
            daemon=True,
        )
        cls._thread.start()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "scheduler_enabled": True,
            "interval_seconds": interval_seconds,
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "BACKGROUND_SCHEDULER_STARTED",
        }

    @classmethod
    def stop(cls):
        cls._enabled = False
        cls._stop_event.set()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "scheduler_enabled": False,
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "BACKGROUND_SCHEDULER_STOPPED",
        }

    @classmethod
    def status(cls):
        cls._load_state()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "scheduler_enabled": cls._enabled,
            "cycle_count": cls._cycle_count,
            "last_run": cls._last_run,
            "last_status": cls._last_status,
            "thread_alive": bool(cls._thread and cls._thread.is_alive()),
            "success_count": cls._success_count,
            "failure_count": cls._failure_count,
            "consecutive_failures": cls._consecutive_failures,
            "cycle_success_rate_pct": (
                round(cls._success_count / (cls._success_count + cls._failure_count) * 100, 2)
                if (cls._success_count + cls._failure_count) else None
            ),
            "last_error": cls._last_error,
            "last_error_at": cls._last_error_at,
            "last_duration_ms": cls._last_duration_ms,
            "recent_cycles": cls._recent_cycles[-10:],
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "BACKGROUND_SCHEDULER_STATUS_READY",
        }

    @classmethod
    def run_once(cls):
        result = cls._run_cycle()
        return result

    @classmethod
    def _run_loop(cls, interval_seconds):
        while not cls._stop_event.is_set():
            try:
                cls._run_cycle()
            except Exception as exc:
                cls._last_run = datetime.utcnow().isoformat()
                cls._last_status = f"BACKGROUND_SCHEDULER_CYCLE_FAILED: {exc}"
                cls._record_result("FAILED", cls._last_run, error=str(exc))
                cls._save_state()
                ImmutableAuditLedgerEngine().record(
                    "BACKGROUND_SCHEDULER_CYCLE_FAILED",
                    {
                        "error": str(exc),
                        "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
                        "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
                    },
                )
            cls._stop_event.wait(interval_seconds)

    @classmethod
    def _run_cycle(cls):
        cls._load_state()
        started = datetime.utcnow().isoformat()

        market_hours = MarketHoursEngine().status()
        token = TradeStationTokenMaintenanceEngine().evaluate()
        decision = DecisionSchedulerEngine().run_manual_cycle()

        try:
            forecast_grading = (
                ForecastOutcomeGraderEngine().grade_pending(
                    min_age_minutes=60
                )
            )
        except Exception as exc:
            forecast_grading = {
                "graded_count": 0,
                "error": repr(exc),
                "status": (
                    "FORECAST_OUTCOME_GRADER_DEGRADED"
                ),
            }

        # limit was 1 — so only ONE symbol's forward price was recorded per cycle, far too
        # sparse to grade against. Quotes are deduped by distinct symbol, so a higher limit
        # widens universe coverage without extra quote calls.
        forward = ForwardOutcomeCaptureEngine().capture(limit=60)
        learning = DecisionLearningMemoryEngine().record_current_learning()

        # Drift-free skill read, persisted as a time series so the edge (or its absence)
        # becomes visible as data accumulates. Grades each decision at T+horizon against the
        # forward price the step above now records — not against "price whenever we ran".
        try:
            fh = FixedHorizonGraderEngine().grade()
            fixed_horizon = {k: fh[k] for k in (
                "horizon_hours", "counts", "graded_count",
                "per_direction", "balanced_accuracy_precision_based",
            )}
            fixed_horizon["mcc"] = (fh.get("skill") or {}).get("mcc")
            append_jsonl(
                Path("app/data/skill/fixed_horizon_history.jsonl"),
                {"timestamp": started, **fixed_horizon},
            )
        except Exception as exc:
            fixed_horizon = {"error": repr(exc), "status": "FIXED_HORIZON_GRADER_DEGRADED"}

        try:
            institutional_snapshot_sweep = (
                InstitutionalSignalSnapshotSweepEngine()
                .run(
                    limit=10,
                    # Auto-on when a UW key is configured: the mission's real
                    # institutional-flow collection. No key -> stays off (no wasted budget).
                    collect_unusual_whales=bool(getenv("UNUSUAL_WHALES_API_KEY")),
                    collect_tradestation=False,
                    include_tradestation_option_chain=False,
                    deduplicate=True,
                )
            )
        except Exception as exc:
            institutional_snapshot_sweep = {
                "symbol_count": 0,
                "snapshot_recorded_count": 0,
                "deduplicated_count": 0,
                "degraded_count": 1,
                "error": repr(exc),
                "execution_impact": "OBSERVATION_ONLY",
                "status": (
                    "INSTITUTIONAL_SIGNAL_"
                    "SNAPSHOT_SWEEP_DEGRADED"
                ),
            }

        try:
            institutional_retraining = (
                InstitutionalRetrainingOrchestratorEngine()
                .run(
                    limit=10,
                    min_age_minutes=60,
                    persist=True,
                )
            )
        except Exception as exc:
            institutional_retraining = {
                "symbol_count": 0,
                "model_ready_count": 0,
                "collecting_count": 0,
                "actionable_count": 0,
                "degraded_count": 1,
                "error": repr(exc),
                "execution_impact": "OBSERVATION_ONLY",
                "status": (
                    "INSTITUTIONAL_RETRAINING_"
                    "ORCHESTRATOR_DEGRADED"
                ),
            }
        # RETIRED: the old coin-flip signal's execution paths. 28 years / 90k samples
        # proved that signal is noise (core_backtest.py), yet these kept opening equity
        # and options trades on it — competing for the risk budget and contaminating the
        # forward edge measurement. Only the validated MomentumReversalRebalanceEngine
        # trades now. Kept as inert status so the cycle-result shape stays stable.
        paper_executor = {"status": "RETIRED_DEAD_SIGNAL", "paper_trade_recorded": False}
        options_executor = {"status": "RETIRED_DEAD_SIGNAL", "paper_trades_recorded": 0}

        # The rebuilt, validated strategy, traded forward. Self-gates: no-op unless the
        # market is open, it's due (~weekly), and execution is enabled. On the first due
        # cycle it opens the top-N; thereafter it realizes and re-selects each cycle it fires.
        # OPTIONS MODE (operator directive): trade the signal's picks as OPTIONS, not
        # shares. When GREYLINE_OPTIONS_MODE=true the equity rebalance is skipped and the
        # options execution engine runs instead — same directional signal, options vehicle,
        # affordability-gated, Dynamic-TPS exit. The equity book already open keeps being
        # managed by the exit manager below until it closes, so this is a clean handover.
        from os import getenv as _getenv
        options_mode = (_getenv("GREYLINE_OPTIONS_MODE", "") or "").lower() == "true"
        if options_mode:
            try:
                from app.services.momentum_options_execution_engine import MomentumOptionsExecutionEngine
                momentum_reversal = MomentumOptionsExecutionEngine().run_cycle()
            except Exception as exc:
                momentum_reversal = {"placed_count": 0, "error": repr(exc),
                                     "status": "MOMENTUM_OPTIONS_REBALANCE_DEGRADED"}
        else:
            try:
                momentum_reversal = MomentumReversalRebalanceEngine().rebalance()
            except Exception as exc:
                momentum_reversal = {"rebalanced": False, "error": repr(exc),
                                     "status": "MOMENTUM_REVERSAL_REBALANCE_DEGRADED"}

        # Validated H2 exit doctrine, applied to open momentum positions every cycle while
        # the market is open (marks to live quotes; stale closed-market marks would misfire
        # stops). This owns exits now — the rebalance only tops up empty slots.
        try:
            if market_hours.get("is_regular_session") is True:
                momentum_exit = MomentumExitManagerEngine().manage_open_positions()
            else:
                momentum_exit = {"managed": 0, "status": "MOMENTUM_EXIT_MARKET_CLOSED"}
        except Exception as exc:
            momentum_exit = {"error": repr(exc), "status": "MOMENTUM_EXIT_MANAGER_DEGRADED"}

        # Age out raw UW snapshots past the retention window (compacting flow first).
        # Self-gates to ~once/day, so this is a no-op most cycles. Best-effort.
        try:
            from app.services.uw_snapshot_retention_engine import UWSnapshotRetentionEngine
            uw_retention = UWSnapshotRetentionEngine().prune()
        except Exception as exc:
            uw_retention = {"pruned": False, "error": repr(exc),
                            "status": "UW_RETENTION_DEGRADED"}
        paper_position_manager = PaperPositionManagerEngine().manage_open_positions()
        options_position_manager = OptionsPositionManagerEngine().manage_open_positions()
        from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
        health = SystemHealthDashboardEngine().status()

        cls._cycle_count += 1
        cls._last_run = started
        cls._last_status = "BACKGROUND_SCHEDULER_CYCLE_COMPLETE"
        cls._record_result("COMPLETE", started)
        cls._save_state()

        ImmutableAuditLedgerEngine().record(
            "BACKGROUND_SCHEDULER_CYCLE",
            {
                "cycle_count": cls._cycle_count,
                "market_state": market_hours.get("state"),
                "market_open": market_hours.get("is_regular_session"),
                "token_maintenance_status": token.get("status"),
                "decision_status": decision.get("status"),
                "forecast_grading_status": (
                    forecast_grading.get("status")
                ),
                "forecast_grades_processed": (
                    forecast_grading.get("graded_count")
                ),
                "forward_outcome_status": forward.get("status"),
                "forward_price_points_recorded": forward.get("price_points_recorded"),
                "learning_memory_status": learning.get("status"),
                "fixed_horizon_skill": fixed_horizon,
                "momentum_reversal_rebalance": momentum_reversal,
                "momentum_exit_manager": momentum_exit,
                "uw_snapshot_retention": uw_retention,
                "institutional_snapshot_sweep_status": (
                    institutional_snapshot_sweep.get(
                        "status"
                    )
                ),
                "institutional_snapshots_recorded": (
                    institutional_snapshot_sweep.get(
                        "snapshot_recorded_count"
                    )
                ),
                "institutional_snapshots_deduplicated": (
                    institutional_snapshot_sweep.get(
                        "deduplicated_count"
                    )
                ),
                "institutional_snapshot_degraded_count": (
                    institutional_snapshot_sweep.get(
                        "degraded_count"
                    )
                ),
                "institutional_retraining_status": (
                    institutional_retraining.get(
                        "status"
                    )
                ),
                "institutional_models_ready": (
                    institutional_retraining.get(
                        "model_ready_count"
                    )
                ),
                "institutional_models_collecting": (
                    institutional_retraining.get(
                        "collecting_count"
                    )
                ),
                "institutional_models_actionable": (
                    institutional_retraining.get(
                        "actionable_count"
                    )
                ),
                "institutional_retraining_degraded_count": (
                    institutional_retraining.get(
                        "degraded_count"
                    )
                ),
                "paper_executor_status": paper_executor.get("status"),
                "paper_trade_recorded": paper_executor.get("paper_trade_recorded"),
                "options_executor_status": options_executor.get("status"),
                "options_paper_trades_recorded": options_executor.get("paper_trades_recorded"),
            "paper_position_manager_status": paper_position_manager.get("status"),
            "paper_positions_checked": paper_position_manager.get("positions_checked"),
            "paper_positions_closed": paper_position_manager.get("positions_closed"),
            "paper_stale_quote_blocked_count": paper_position_manager.get("stale_quote_blocked_count"),
            "paper_stale_quote_blocked": paper_position_manager.get("stale_quote_blocked"),
            "options_position_manager_status": options_position_manager.get("status"),
            "options_positions_checked": options_position_manager.get("positions_checked"),
            "options_positions_closed": options_position_manager.get("positions_closed"),
                "system_health_status": health.get("status"),
                "overall_health": health.get("overall_health"),
            },
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "BACKGROUND_SCHEDULER",
            "cycle_started": started,
            "cycle_count": cls._cycle_count,
            "market_state": market_hours.get("state"),
            "market_open": market_hours.get("is_regular_session"),
            "token_maintenance_status": token.get("status"),
            "decision_status": decision.get("status"),
            "forecast_grading_status": (
                forecast_grading.get("status")
            ),
            "forecast_grades_processed": (
                forecast_grading.get("graded_count")
            ),
            "forward_outcome_status": forward.get("status"),
            "learning_memory_status": learning.get("status"),
            "institutional_snapshot_sweep": (
                institutional_snapshot_sweep
            ),
            "institutional_retraining": (
                institutional_retraining
            ),
            "paper_executor_status": paper_executor.get("status"),
            "paper_trade_recorded": paper_executor.get("paper_trade_recorded"),
            "options_executor_status": options_executor.get("status"),
            "options_paper_trades_recorded": options_executor.get("paper_trades_recorded"),
            "paper_position_manager_status": paper_position_manager.get("status"),
            "paper_positions_checked": paper_position_manager.get("positions_checked"),
            "paper_positions_closed": paper_position_manager.get("positions_closed"),
            "paper_stale_quote_blocked_count": paper_position_manager.get("stale_quote_blocked_count"),
            "paper_stale_quote_blocked": paper_position_manager.get("stale_quote_blocked"),
            "options_position_manager_status": options_position_manager.get("status"),
            "options_positions_checked": options_position_manager.get("positions_checked"),
            "options_positions_closed": options_position_manager.get("positions_closed"),
            "options_stale_quote_blocked_count": options_position_manager.get("stale_quote_blocked_count"),
            "options_stale_quote_blocked": options_position_manager.get("stale_quote_blocked"),
            "system_health_status": health.get("status"),
            "overall_health": health.get("overall_health"),
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "BACKGROUND_SCHEDULER_CYCLE_COMPLETE",
        }
