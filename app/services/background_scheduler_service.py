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

        # Conditional-VRP short-premium (defined-risk iron condors). GATED OFF by default. When
        # armed: MANAGE open condors every cycle (take-profit / expiry / hard-stop), and OPEN new
        # ones at most once/day, only in a regular session, on a bounded liquid name set (where any
        # VRP concentrates) with a small limit. Every position is defined-risk; the portfolio cap
        # bounds the correlated tail.
        try:
            from pathlib import Path as _P
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
            _sp = ConditionalVRPShortPremiumEngine()
            if not _sp.enabled():
                vrp_short_premium = {"status": "VRP_SHORT_PREMIUM_DISABLED"}
            else:
                vrp_short_premium = {"manage": _sp.manage_positions(dry_run=False)}
                _mk = _P("app/data/options_paper_trading/.vrp_short_last_open")
                _today = datetime.utcnow().date().isoformat()
                _due = True
                try:
                    _due = _mk.read_text().strip() != _today
                except Exception:
                    _due = True
                from app.services.market_hours_engine import MarketHoursEngine
                if _due and MarketHoursEngine().status().get("is_regular_session"):
                    # Sell premium where the variance premium demonstrably LIVES: the measured,
                    # distinct-underlying high-VRP index harvest set (dispersion study 2026-07-26;
                    # firmed by block bootstrap, CI [+1.48,+3.66] vol pts). Single names + defensive
                    # sectors + redundant S&P clones excluded — they carry cost without premium.
                    from app.services.conditional_vrp_short_premium_engine import INDEX_ETFS
                    vrp_short_premium["open"] = _sp.open_positions(names=INDEX_ETFS, dry_run=False, limit=2)
                    try:
                        _mk.parent.mkdir(parents=True, exist_ok=True); _mk.write_text(_today)
                    except Exception:
                        pass
        except Exception as exc:
            vrp_short_premium = {"status": "VRP_SHORT_PREMIUM_DEGRADED", "error": repr(exc)}

        # Phase 2: reconcile pending limit-buy fills and refine the entry aggressiveness.
        try:
            from app.services.options_entry_reconciler_engine import OptionsEntryReconcilerEngine
            _reconciler = OptionsEntryReconcilerEngine()
            options_entry_reconcile = _reconciler.reconcile()
            # Then heal any OPEN entry the broker neither holds nor has a working order for.
            # A rejected limit order (our first live ones were rejected for an invalid price
            # increment) otherwise leaves the ledger claiming a position that never existed —
            # the exact fantasy state the Reality Guard is there to catch.
            options_entry_reconcile["phantom_sweep"] = _reconciler.sweep_phantoms()
        except Exception as exc:
            options_entry_reconcile = {"status": "OPTIONS_ENTRY_RECONCILE_DEGRADED", "error": repr(exc)}

        # Exit side: resolve priced exit fills and measure realized price vs mid and vs the old
        # naked-market counterfactual — the evidence that the exit-pricing change actually pays.
        try:
            from app.services.options_exit_reconciler_engine import OptionsExitReconcilerEngine
            options_exit_reconcile = OptionsExitReconcilerEngine().reconcile()
        except Exception as exc:
            options_exit_reconcile = {"status": "OPTIONS_EXIT_RECONCILE_DEGRADED", "error": repr(exc)}

        # Conditional-VRP forward panel: record today's rich-IV/non-earnings entries and resolve
        # any whose 30-day window has closed. This is the OUT-OF-SAMPLE test that earns the p-value
        # the backtest could not. Self-gated to once/day (UW budget); resolve runs every cycle since
        # it is cheap and only acts on completed windows.
        try:
            from pathlib import Path as _P
            from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine
            _vp = ConditionalVRPForwardPanelEngine()
            _marker = _P("app/data/research/.vrp_panel_last_record")
            _today = datetime.utcnow().date().isoformat()
            _due = True
            try:
                _due = _marker.read_text().strip() != _today
            except Exception:
                _due = True
            vrp_panel = {"record": (_vp.record_signals() if _due else {"status": "VRP_RECORD_NOT_DUE"})}
            if _due:
                try:
                    _marker.parent.mkdir(parents=True, exist_ok=True); _marker.write_text(_today)
                except Exception:
                    pass
            vrp_panel["resolve"] = _vp.resolve()
        except Exception as exc:
            vrp_panel = {"status": "VRP_PANEL_DEGRADED", "error": repr(exc)}

        # Index variance premium forward panel — the OUT-OF-SAMPLE arbiter for THE candidate (the
        # one edge that cleared significance). Records the index harvest set daily, resolves ~30d
        # out. Self-gated to once/day for the record (UW budget); resolve is cheap, runs each cycle.
        try:
            from pathlib import Path as _P2
            from app.services.index_variance_premium_panel_engine import IndexVariancePremiumPanelEngine
            _ivp = IndexVariancePremiumPanelEngine()
            _m2 = _P2("app/data/research/.index_vrp_last_record")
            _t2 = datetime.utcnow().date().isoformat()
            _due2 = True
            try:
                _due2 = _m2.read_text().strip() != _t2
            except Exception:
                _due2 = True
            index_vrp_panel = {"record": (_ivp.record() if _due2 else {"status": "NOT_DUE"}),
                               "resolve": _ivp.resolve()}
            if _due2:
                try:
                    _m2.parent.mkdir(parents=True, exist_ok=True); _m2.write_text(_t2)
                except Exception:
                    pass
        except Exception as exc:
            index_vrp_panel = {"status": "INDEX_VRP_PANEL_DEGRADED", "error": repr(exc)}

        # Full-history price-bar integrity scan. Self-gates to ~once/day, so this is a no-op
        # most cycles; it keeps the Reality Guard's PRICE_BARS_CLEAN invariant backed by all
        # 3.4M rows rather than a 30-row window. Corrupt bars silently poison ATR/stops/TPs.
        try:
            from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine
            price_bar_scan = PriceBarIntegrityEngine().scan_if_due()
        except Exception as exc:
            price_bar_scan = {"status": "PRICE_BAR_SCAN_DEGRADED", "error": repr(exc)}

        # Lineage: has any SETTLED historical bar silently changed since the accepted baseline?
        # This is the reproducibility guard — it catches vendor restatements / re-adjustments /
        # corruption that every other (point-in-time) check is blind to. Bootstraps its
        # baseline on first run, then self-gates to ~once a day.
        try:
            from app.services.price_bar_lineage_engine import PriceBarLineageEngine
            lineage = PriceBarLineageEngine().verify_if_due()
        except Exception as exc:
            lineage = {"status": "LINEAGE_VERIFY_DEGRADED", "error": repr(exc)}

        # Options reality capture. The options mission cannot be backtested (no historical
        # contract data exists from UW or TradeStation), so this forward panel is the only
        # evidence an options edge can ever be verified against. A missed day is permanent.
        try:
            from app.services.options_reality_capture_engine import OptionsRealityCaptureEngine
            options_capture = OptionsRealityCaptureEngine().capture_if_due()
        except Exception as exc:
            options_capture = {"status": "OPTIONS_CAPTURE_DEGRADED", "error": repr(exc)}

        # Earnings implied-vs-realized: the first candidate that passes the ECONOMIC MAGNITUDE
        # screen (28.7% of earnings moves exceed the 6% OTM-viable threshold). The implied side
        # is unrecoverable after the fact, so it must be recorded before each announcement.
        try:
            from app.services.earnings_vol_edge_engine import EarningsVolEdgeEngine
            _ev = EarningsVolEdgeEngine()
            earnings_vol = _ev.record_implied()
            earnings_vol["resolved"] = _ev.resolve_realized().get("resolved")
        except Exception as exc:
            earnings_vol = {"status": "EARNINGS_VOL_DEGRADED", "error": repr(exc)}

        # Off-machine backup of the UNRECOVERABLE data (options surface, PIT archive, panels,
        # ledgers). ~5MB, forward-only, no API can rebuild it — one disk failure would restart
        # the options edge experiment from zero.
        try:
            from app.services.disaster_recovery_engine import DisasterRecoveryEngine
            _dr = DisasterRecoveryEngine()
            _last = _dr.last_backup()
            _due = True
            if _last:
                try:
                    _due = (datetime.utcnow() - datetime.fromisoformat(_last["timestamp"])).total_seconds() > 20 * 3600
                except Exception:
                    _due = True
            backup = _dr.backup() if _due else {"status": "BACKUP_NOT_DUE"}
        except Exception as exc:
            backup = {"status": "BACKUP_DEGRADED", "error": repr(exc)}
        # The proof case: a backup that fails must SCREAM, not sit in a ledger reading "complete".
        # A CRITICAL notification now auto-escalates off the machine (if a channel is configured).
        if str(backup.get("status")) in ("BACKUP_DEGRADED", "BACKUP_INCOMPLETE"):
            try:
                from app.services.operator_notification_engine import OperatorNotificationEngine
                OperatorNotificationEngine().record(
                    event_type="BACKUP_FAILED",
                    title="Off-machine backup FAILED",
                    message=(f"Unrecoverable-data backup returned {backup.get('status')}. "
                             f"Forward-only data (options surface, PIT archive, earnings panel) "
                             f"is unprotected until this is fixed. {str(backup.get('error') or '')[:150]}"),
                    severity="CRITICAL", source="DISASTER_RECOVERY", payload=backup)
            except Exception:
                pass

        # Broker-side disaster stops: the only protection that survives THIS process dying.
        # Every doctrine exit (ATR stop, TP ladder, maturity liquidation) needs the scheduler
        # alive; a resting GTC stop at the broker does not. Default OFF, and each cycle it only
        # covers positions that lack a working sell (never stacks on a close — double-sell guard).
        try:
            from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
            _bp = BrokerProtectiveStopEngine()
            broker_stops = _bp.ensure_stops() if _bp.enabled() else _bp.status()
        except Exception as exc:
            broker_stops = {"status": "BROKER_STOPS_DEGRADED", "error": repr(exc)}

        # Second-source proof: the integrity scan only checks the CSVs against THEMSELVES.
        # Uniformly-wrong data (a shift, a mis-mapped ticker, an unadjusted split) is
        # self-consistent and invisible to it — and these CSVs are what every signal, ATR,
        # stop and TP is computed from. Rotating sample, self-gated to ~once a day.
        try:
            from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine
            cross_source = PriceBarCrossSourceEngine().reconcile_if_due()
        except Exception as exc:
            cross_source = {"status": "CROSS_SOURCE_DEGRADED", "error": repr(exc)}

        # Which bars were actually TRADED. Pre-listing stubs are self-consistent, match the
        # vendor, and are still unusable — they manufacture fake momentum in backtests and
        # would let a name into the universe on a handful of real bars.
        try:
            from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
            tradability = PriceBarTradabilityEngine().scan()
        except Exception as exc:
            tradability = {"status": "TRADABILITY_SCAN_DEGRADED", "error": repr(exc)}

        # Survivorship: record today's universe point-in-time and RETAIN any symbol whose
        # feed goes quiet. Delisted-company prices can't be bought back later — TradeStation
        # purges them — so the only way to own a survivorship-free dataset is to stop
        # discarding names as they die, starting now.
        try:
            from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine
            _surv = UniverseSurvivorshipEngine()
            survivorship = _surv.snapshot()
            survivorship["departures"] = _surv.detect_departures()
        except Exception as exc:
            survivorship = {"status": "SURVIVORSHIP_ARCHIVE_DEGRADED", "error": repr(exc)}
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
                "price_bar_cross_source_status": cross_source.get("status"),
                "lineage_status": lineage.get("status"),
                "options_capture_status": options_capture.get("status"),
                "earnings_vol_status": earnings_vol.get("status"),
                "backup_status": backup.get("status"),
                "broker_stops_status": broker_stops.get("status"),
                "broker_stops_placed": broker_stops.get("placed"),
                "broker_stops_unprotected": broker_stops.get("unprotected"),
                "options_exit_reconcile_status": options_exit_reconcile.get("status"),
                "options_exit_reconcile_filled": options_exit_reconcile.get("filled"),
                "vrp_panel_recorded": (vrp_panel.get("record") or {}).get("recorded"),
                "vrp_short_premium_status": vrp_short_premium.get("status") or "VRP_SHORT_PREMIUM_ACTIVE",
                "vrp_short_premium_opened": ((vrp_short_premium.get("open") or {}) if isinstance(vrp_short_premium.get("open"), dict) else {}).get("opened"),
                "vrp_panel_resolved": (vrp_panel.get("resolve") or {}).get("resolved"),
                "index_vrp_recorded": (index_vrp_panel.get("record") or {}).get("recorded"),
                "index_vrp_resolved": (index_vrp_panel.get("resolve") or {}).get("resolved"),
                "earnings_vol_recorded": earnings_vol.get("recorded"),
                "options_capture_rows": options_capture.get("rows"),
                "lineage_changed": lineage.get("changed_count"),
                "tradability_status": tradability.get("status"),
                "survivorship_archive_status": survivorship.get("status"),
                "tradability_excluded": tradability.get("contaminated_signal_windows"),
                "price_bar_cross_source_mismatched": cross_source.get("mismatched"),
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
