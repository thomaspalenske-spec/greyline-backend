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
from app.services.env_reload import uw_api_key
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
    _phase_marks = []                # [(label, monotonic)] within the CURRENT cycle
    _last_phase_timings = {}         # {phase: seconds} from the last COMPLETED cycle — for /status
    _CYCLE_COST_CAP = 500            # cycle-cost history is a rolling window (steady-state vs one-off)
    CYCLE_COST_HISTORY = Path("app/data/scheduler/cycle_cost_history.jsonl")

    @classmethod
    def _phase_reset(cls):
        cls._phase_marks = [("_start", time.monotonic())]

    @classmethod
    def _ckpt(cls, label):
        """Record a phase-boundary timestamp. BULLETPROOF: a timing checkpoint must NEVER be able to
        break the trading cycle, so every failure is swallowed."""
        try:
            cls._phase_marks.append((str(label), time.monotonic()))
        except Exception:
            pass

    @classmethod
    def _persist_cycle_cost(cls, duration_ms, status):
        """Append the finalized per-phase breakdown to a rolling history so steady-state vs a one-off
        hiccup is VISIBLE (the /status card only shows the last cycle — in-memory). BULLETPROOF: a
        timing log must never break the cycle, so every failure is swallowed. Bounded to the last
        _CYCLE_COST_CAP cycles."""
        try:
            import json
            timings = dict(cls._last_phase_timings or {})
            if not timings:
                return
            rec = {"timestamp": datetime.utcnow().isoformat(), "status": status,
                   "duration_ms": duration_ms,
                   "cycle_seconds": round((duration_ms or 0) / 1000.0, 1),
                   "phases": {k: v for k, v in timings.items() if k != "_total_instrumented"},
                   "instrumented_seconds": timings.get("_total_instrumented")}
            cls.CYCLE_COST_HISTORY.parent.mkdir(parents=True, exist_ok=True)
            try:
                lines = cls.CYCLE_COST_HISTORY.read_text().splitlines() if cls.CYCLE_COST_HISTORY.exists() else []
            except Exception:
                lines = []
            lines.append(json.dumps(rec))
            cls.CYCLE_COST_HISTORY.write_text("\n".join(lines[-cls._CYCLE_COST_CAP:]) + "\n")
        except Exception:
            pass

    @classmethod
    def cycle_cost_history(cls, limit=50):
        """Summarize the rolling cycle-cost history so STEADY-STATE (median/p90 per phase) is
        distinguishable from a one-off spike (max) — the /status card only shows the last cycle.
        READ-ONLY. Ranks phases by median cost = the real optimization target."""
        import json
        from collections import defaultdict
        try:
            rows = [json.loads(l) for l in cls.CYCLE_COST_HISTORY.read_text().splitlines() if l.strip()]
        except Exception:
            rows = []
        rows = rows[-max(1, int(limit or 50)):]
        buckets = defaultdict(list)
        for r in rows:
            for ph, sec in (r.get("phases") or {}).items():
                try:
                    buckets[ph].append(float(sec))
                except (TypeError, ValueError):
                    pass

        def _pct(vals, q):
            if not vals:
                return None
            s = sorted(vals)
            return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1)

        summary = {ph: {"n": len(v), "median_s": _pct(v, 0.5), "p90_s": _pct(v, 0.9),
                        "max_s": round(max(v), 1)} for ph, v in buckets.items()}
        ranked = sorted(summary.items(), key=lambda kv: (kv[1]["median_s"] or 0), reverse=True)
        cyc = [r.get("cycle_seconds") for r in rows if r.get("cycle_seconds") is not None]
        return {
            "cycles_in_window": len(rows),
            "cycle_seconds": {"median": _pct(cyc, 0.5), "p90": _pct(cyc, 0.9),
                              "max": round(max(cyc), 1) if cyc else None,
                              "last": rows[-1].get("cycle_seconds") if rows else None},
            "phase_cost_ranked_by_median": [{"phase": ph, **st} for ph, st in ranked],
            "recent": rows[-10:],
            "status": "SCHEDULER_CYCLE_COST_HISTORY",
        }

    @classmethod
    def _phase_finalize(cls):
        """Turn the checkpoint marks into {phase: seconds} (consecutive deltas) + an instrumented total.
        The uninstrumented remainder shows up as the gap between _total_instrumented and duration_ms."""
        try:
            marks = cls._phase_marks or []
            timings = {}
            for i in range(1, len(marks)):
                timings[marks[i][0]] = round(marks[i][1] - marks[i - 1][1], 2)
            if len(marks) >= 2:
                timings["_total_instrumented"] = round(marks[-1][1] - marks[0][1], 2)
            cls._last_phase_timings = timings
            return timings
        except Exception:
            return {}

    @classmethod
    def _heavy_recompute_blocked(cls, market_hours):
        """The 5 non-critical trend_mf_carry recomputes (best-condors dashboard card, condor/mf shadows,
        once-day universe/sector refresh) do minutes-long serial UW/TS chain work — NONE of it on the
        trade-firing path (the sleeves fire in their own fast phases). Measured: this block is ~164 min,
        96% of the whole cycle. If one runs in the pre-open→session window it saturates TradeStation and
        STARVES the broker read exactly when the exposure breaker needs it, failing the gate CLOSED and
        blocking the open. So on trading days block them from a pre-open cutoff (default 05:00 ET — early
        enough that no single ~170-min heavy phase can still be running at 09:30) through the 16:00 close.
        They still run overnight and post-close, which matches their natural once-day / settled-bar
        cadence anyway (only best-condors wanted intraday freshness, and it's just a card).

        Fail-OPEN (allow) if the ET clock can't be resolved, so a transient market-hours glitch never
        silently freezes the dashboard/forward-tests — the broker-read bounded retry is the open-day
        backstop in that rare case. Returns (blocked: bool, reason: str)."""
        try:
            from datetime import datetime as _dt, time as _time
            mt = market_hours.get("market_time") if isinstance(market_hours, dict) else None
            now_et = _dt.fromisoformat(mt) if mt else None
            if now_et is None or not market_hours.get("is_weekday") or market_hours.get("is_holiday"):
                return (False, "off-hours/weekend/holiday — heavy recomputes allowed")

            def _hhmm(s, dflt):
                try:
                    hh, mm = str(s).split(":")
                    return _time(int(hh), int(mm))
                except Exception:
                    return dflt
            block_from = _hhmm(getenv("GREYLINE_HEAVY_RECOMPUTE_BLOCK_FROM", "05:00"), _time(5, 0))
            block_until = _hhmm(getenv("GREYLINE_HEAVY_RECOMPUTE_BLOCK_UNTIL", "16:00"), _time(16, 0))
            if block_from <= now_et.time() <= block_until:
                return (True, "open-window guard %s-%s ET (now %s) — deferred so a slow chain scan can't "
                              "starve the broker read at the open" % (block_from.strftime("%H:%M"),
                              block_until.strftime("%H:%M"), now_et.time().strftime("%H:%M")))
            return (False, "outside open-window — heavy recomputes allowed")
        except Exception as exc:
            return (False, "guard error (fail-open): %s" % repr(exc)[:80])

    @classmethod
    def _intraday_shadow_deferred(cls, heavy_blocked):
        """The gex-walls-fade and vanna shadows need LIVE intraday quotes to open, so unlike the 164-min chain
        scans they must NOT inherit the full _heavy_blocked RTH defer (which would leave them able to run only
        overnight, when equity_session_open() fail-closes them → they'd never act; that's why gex showed 0
        positions). They are safe intraday: each self-gates to hourly (MARK_INTERVAL_MIN=60) and fail-closes
        off-session, so near the open they add at most a few batched TS quotes + a cached UW gamma read once an
        hour — they can't straddle the open or starve the broker read. Allowed through RTH by default; the escape
        hatch GREYLINE_INTRADAY_SHADOWS_RTH=false restores the old heavy-defer if TS/UW throttling is observed.
        Returns True only when the heavy gate is active AND the exemption is disabled."""
        if not heavy_blocked:
            return False
        return (getenv("GREYLINE_INTRADAY_SHADOWS_RTH", "true") or "true").strip().lower() != "true"

    INSTITUTIONAL_LAST_RUN = Path("app/data/institutional/.institutional_pipeline_last_run")

    @classmethod
    def _institutional_pipeline_due(cls, market_hours):
        """The institutional-flow retrain + sweep dominate cycle cost (~940s cold / ~59% — measured
        2026-08-14) yet are OBSERVATION_ONLY (fire no trades) and target the UNPROVEN flow edge. So run
        them at most ONCE per day and only OUTSIDE the open window (reusing the heavy-recompute guard),
        never on the intraday hot path where they slow every 5-min cycle and can straddle the open.
        GREYLINE_INSTITUTIONAL_PER_CYCLE=true restores the old every-cycle behavior. Returns (due, reason)."""
        if (getenv("GREYLINE_INSTITUTIONAL_PER_CYCLE", "") or "").strip().lower() == "true":
            return (True, "per-cycle override on")
        blocked, why = cls._heavy_recompute_blocked(market_hours)
        if blocked:
            return (False, "deferred to off-hours — " + why)
        try:
            today = datetime.utcnow().date().isoformat()
            if cls.INSTITUTIONAL_LAST_RUN.exists() and cls.INSTITUTIONAL_LAST_RUN.read_text().strip() == today:
                return (False, "already ran today (%s)" % today)
        except Exception:
            pass
        return (True, "off-hours and not yet run today")

    @classmethod
    def _stamp_institutional_run(cls):
        """Mark the institutional pipeline as run for today (bulletproof — never breaks the cycle)."""
        try:
            cls.INSTITUTIONAL_LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
            cls.INSTITUTIONAL_LAST_RUN.write_text(datetime.utcnow().date().isoformat())
        except Exception:
            pass

    @staticmethod
    def _day_marker_due(rel):
        """READ-ONLY: True unless the daily marker at `rel` already carries today's UTC date. FAIL-OPEN
        (returns True on any read error) so a broken marker degrades to running the task, never to silently
        skipping integrity/survivorship work — a missed survivorship snapshot is permanent data loss."""
        try:
            mk = Path(rel)
            return not (mk.exists() and mk.read_text().strip() == datetime.utcnow().date().isoformat())
        except Exception:
            return True

    @staticmethod
    def _day_marker_stamp(rel):
        """Stamp the daily marker at `rel` with today's UTC date — call only AFTER the task succeeds, so a
        transient failure still retries next cycle. Bulletproof."""
        try:
            mk = Path(rel)
            mk.parent.mkdir(parents=True, exist_ok=True)
            mk.write_text(datetime.utcnow().date().isoformat())
        except Exception:
            pass

    _ALERT_AFTER_FAILURES = 3        # consecutive cycle failures before alerting off-box (~15 min)

    @classmethod
    def _alert_cycle_failures(cls, consecutive, error):
        """Best-effort off-box alert that the scheduler cycle is failing. Only fires when an EXTERNAL
        channel is configured — a macOS-local popup is useless when the box itself is the problem."""
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            eng.dispatch(
                title="GreyLine scheduler FAILING",
                message=(f"{consecutive} consecutive cycle failures — nothing is trading/managing. "
                         f"Last error: {str(error)[:140]}"),
                severity="CRITICAL",
                fingerprint=f"SCHED_CYCLE_FAIL:{str(error)[:40]}",
            )
        except Exception:
            pass

    @classmethod
    def _watch_cycle_duration(cls, duration_ms):
        """Off-box alert when a cycle runs PATHOLOGICALLY long — a long cycle can straddle the market open
        and misfire. Fires when the cycle wall-clock OR any single phase crosses its threshold, naming the
        dominant phase from the timing instrument. Thresholds default ABOVE the normal 7-14min band so a
        healthy cycle never pages (env: GREYLINE_CYCLE_SLOW_SECONDS / GREYLINE_PHASE_SLOW_SECONDS). Deduped
        by (dominant phase + a 2-min duration bucket) so it pages once per NEW/worsening slow-state, not
        every cycle. Best-effort; gated on an external channel (a local popup is useless if the box hangs)."""
        try:
            if duration_ms is None:
                return
            cyc_s = duration_ms / 1000.0
            try:
                cyc_thr = float(getenv("GREYLINE_CYCLE_SLOW_SECONDS", "") or 1200)   # 20 min > normal band
            except (TypeError, ValueError):
                cyc_thr = 1200.0
            try:
                phase_thr = float(getenv("GREYLINE_PHASE_SLOW_SECONDS", "") or 600)  # a single phase >10 min
            except (TypeError, ValueError):
                phase_thr = 600.0
            timings = {k: v for k, v in (cls._last_phase_timings or {}).items() if k != "_total_instrumented"}
            dominant, dsecs = (max(timings.items(), key=lambda kv: kv[1]) if timings else (None, 0.0))
            if cyc_s <= cyc_thr and not (dominant is not None and dsecs > phase_thr):
                return
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            dom_txt = f"{dominant} {dsecs:.0f}s" if dominant else "n/a (no phase timing)"
            eng.dispatch(
                title="GreyLine scheduler cycle SLOW",
                message=(f"cycle {cyc_s:.0f}s (threshold {cyc_thr:.0f}s) — dominant phase {dom_txt}. A long "
                         "cycle can straddle the open and misfire; see /background-scheduler/status timings."),
                severity="WARNING",
                # dedup by dominant phase + a 2-min bucket, so a WORSENING cycle re-pages but a steady one doesn't
                fingerprint=f"SCHED_CYCLE_SLOW:{dominant or 'cycle'}:{int(cyc_s // 120)}",
            )
        except Exception:
            pass

    @classmethod
    def _alert_cycle_recovered(cls, prev_failures):
        """Tell the operator the cycle is healthy again after a failing streak."""
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            eng.dispatch(
                title="GreyLine scheduler recovered",
                message=f"cycle succeeded after {prev_failures} consecutive failures",
                severity="INFO", fingerprint="SCHED_CYCLE_RECOVERED", force=True,
            )
        except Exception:
            pass

    # Status substrings that mean "this step RAN and BROKE" vs "nothing to do". Only faults alert.
    _FAULT_MARKERS = ("DEGRADED", "ERROR", "STALE", "_FAIL", "FAILED", "EXCEPTION", "UNBOUND")
    _BENIGN_MARKERS = ("NOT_DUE", "DISABLED", "NO_SIGNAL", "MARKET_CLOSED", "ONCE", "ALREADY", "SKIPPED_NOT")

    @classmethod
    def _watch_armed_sleeve_faults(cls, market_hours, sleeve_statuses):
        """During a REGULAR SESSION, alert off-box if any sleeve or pre-sleeve step FAULTED (degraded,
        stale, errored) even though the cycle recorded COMPLETE — the 'looks fine but silently didn't
        trade' surface, and the exact class the #2 try-wrapping would otherwise turn from a loud
        3-strikes failure into a silent degrade. Benign skips (not-due, disabled, no-signal, market-
        closed) are ignored so it can't spam. dispatch()'s fingerprint cooldown throttles repeats;
        a new set of faulting steps re-alerts."""
        try:
            if not market_hours.get("is_regular_session"):
                return
            faulted = []
            for name, status in sleeve_statuses.items():
                s = str(status or "").upper()
                if not s or any(b in s for b in cls._BENIGN_MARKERS):
                    continue
                if any(f in s for f in cls._FAULT_MARKERS):
                    faulted.append(f"{name}={status}")
            if not faulted:
                return
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            eng.dispatch(
                title="GreyLine sleeve FAULTED during session",
                message=("cycle COMPLETED but these armed steps did not run clean (possible silent "
                         "non-trade): " + "; ".join(faulted[:8])),
                severity="CRITICAL",
                fingerprint="SLEEVE_FAULT:" + ",".join(sorted(f.split("=")[0] for f in faulted)),
            )
        except Exception:
            pass

    @classmethod
    def _record_result(cls, status, started, error=None):
        try:
            start_dt = datetime.fromisoformat(started) if isinstance(started, str) else started
            duration_ms = int((datetime.utcnow() - start_dt).total_seconds() * 1000)
        except Exception:
            duration_ms = None

        cls._last_duration_ms = duration_ms
        cls._persist_cycle_cost(duration_ms, status)   # rolling history: steady-state vs one-off hiccup
        if status == "COMPLETE":
            prev_failures = cls._consecutive_failures
            cls._success_count += 1
            cls._consecutive_failures = 0
            # last_error is "the error from the LAST cycle" — clear it on success so a long-since-FIXED
            # failure (e.g. the 2026-07-26 MarketHoursEngine bug) stops rendering as a live problem in
            # /background-scheduler/status and the reality guard weeks after it was resolved.
            cls._last_error = None
            cls._last_error_at = None
            if prev_failures >= cls._ALERT_AFTER_FAILURES:
                cls._alert_cycle_recovered(prev_failures)      # tell the operator it's back
            cls._watch_cycle_duration(duration_ms)             # page if the cycle ran pathologically long
        else:
            cls._failure_count += 1
            cls._consecutive_failures += 1
            cls._last_error = error
            cls._last_error_at = datetime.utcnow().isoformat()
            # FORENSICS: last_error is cleared on the next success, so without this the failure leaves no
            # trace beyond the count. Persist a classified record (error class, failure-locus phase, signed
            # minutes-to-open) so the ~8% failure rate becomes diagnosable and near-open (entry-threatening)
            # failures are countable. Best-effort — never let bookkeeping turn a failure into a crash.
            try:
                from app.services.cycle_failure_forensics_engine import CycleFailureForensicsEngine
                CycleFailureForensicsEngine.record(
                    error, phase_hint=CycleFailureForensicsEngine._phase_hint_from_timings(cls._last_phase_timings))
            except Exception:
                pass
            # MAKE SILENT FAILURES LOUD: the cycle self-gates when the market is closed, so a total
            # failure is invisible from outside (it hid for 25h / 303 cycles on 2026-07-26). Alert
            # OFF the box after a few consecutive failures; the dispatch's fingerprint cooldown keeps
            # it from spamming every cycle, and a new error type re-alerts.
            if cls._consecutive_failures >= cls._ALERT_AFTER_FAILURES:
                cls._alert_cycle_failures(cls._consecutive_failures, error)

        entry = {"status": status, "at": datetime.utcnow().isoformat(), "duration_ms": duration_ms,
                 "error": error, "phase_timings": cls._last_phase_timings or {}}
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

    _LIVE_FRESH_SECONDS = 1200      # a persisted cycle within ~3-4 intervals proves the live scheduler runs

    @classmethod
    def scheduler_live(cls):
        """CROSS-PROCESS scheduler liveness — use THIS in health/readiness checks, never raw `thread_alive`.
        `thread_alive` is PROCESS-LOCAL (False from any other process — a route worker, a scheduled job, a
        one-off script), so checks that trusted it falsely reported 'scheduler down' out-of-process. This
        returns True if the in-process thread is alive OR the scheduler's OWN persisted output shows a recent
        cycle. LIVENESS only (is it running) — health/success is consecutive_failures' job, kept separate.
        Reads state files directly (never mutates the live class attrs)."""
        try:
            if cls._thread is not None and cls._thread.is_alive():
                return True
        except Exception:
            pass
        from datetime import datetime as _dt

        def _fresh(ts):
            try:
                return (_dt.utcnow() - _dt.fromisoformat(str(ts))).total_seconds() <= cls._LIVE_FRESH_SECONDS
            except Exception:
                return False
        # (a) per-cycle persisted output — timestamped every completed cycle
        try:
            import json as _json
            lines = [l for l in cls.CYCLE_COST_HISTORY.read_text().splitlines() if l.strip()]
            if lines and _fresh(_json.loads(lines[-1]).get("timestamp")):
                return True
        except Exception:
            pass
        # (b) persisted scheduler state — read WITHOUT mutating the live class attrs
        try:
            st = read_json(cls._state_file, default=dict) or {}
            if _fresh(st.get("last_run")):
                return True
        except Exception:
            pass
        return False

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

        # Gated-OFF quote STREAM cache-warmer (its own daemon thread; no-op unless
        # GREYLINE_TS_QUOTE_STREAM_ENABLED). Pure optimization — REST is the fallback, so a failure here
        # never touches the cycle. Isolated in try/except so it can't block the scheduler from starting.
        try:
            from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine
            TradeStationQuoteStreamEngine.start_if_enabled()
        except Exception:
            pass

        # Positions stream cache-warmer (gated GREYLINE_TS_BROKER_STREAM_ENABLED). Warms the positions
        # cache ONLY while a REST cross-check agrees; any doubt -> REST fallback, so a failure here never
        # touches the cycle. Isolated so it can't block the scheduler from starting.
        try:
            from app.services.tradestation_broker_stream_engine import TradeStationBrokerStreamEngine
            TradeStationBrokerStreamEngine.start_if_enabled()
        except Exception:
            pass

        # UW WebSocket push-feed cache-warmer (gated GREYLINE_UW_STREAM_ENABLED). Additive — warms its own
        # UW cache; no read path depends on it, so a failure here never touches the cycle. Isolated so it
        # can't block the scheduler from starting.
        try:
            from app.services.uw_stream_engine import UWStreamEngine
            UWStreamEngine.start_if_enabled()
        except Exception:
            pass

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
        # Read-only token health so the dashboard's "Token" readiness tile reflects reality instead of
        # sitting permanently on "CHECK" (this key was consumed by the template but never produced).
        # evaluate() only READS the stored token file — it does NOT trigger a refresh (see the
        # token-over-refresh incident), so it is safe to call on every 15s status poll. Unknown token
        # state falls to "CHECK" (yellow), never a false green.
        try:
            from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine
            _tok = TradeStationTokenStatusEngine().evaluate()
            token_status = "READY" if _tok.get("ready_for_read_only") else "NOT_READY"
        except Exception:
            token_status = "CHECK"
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "token_status": token_status,
            # Reflects THIS (running scheduler) process's view of the flag — so the next condor open/close
            # this scheduler does will be a single atomic multi-leg order when true.
            "condor_atomic_orders": (getenv("GREYLINE_CONDOR_ATOMIC_ORDER", "") or "").strip().lower() == "true",
            "scheduler_enabled": cls._enabled,
            "cycle_count": cls._cycle_count,
            "last_run": cls._last_run,
            "last_status": cls._last_status,
            "thread_alive": bool(cls._thread and cls._thread.is_alive()),
            # CROSS-PROCESS liveness — health/readiness checks must gate on THIS, not the process-local
            # thread_alive above, so an out-of-process audit never false-reports 'scheduler down'.
            "scheduler_live": cls.scheduler_live(),
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
            # per-phase wall-clock of the last cycle (seconds): which phase dominates the cycle time.
            # The gap between _total_instrumented and last_duration_ms/1000 is uninstrumented remainder.
            "last_phase_timings": cls._last_phase_timings or {},
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
    def _next_interval(cls, interval_seconds, failed):
        """Wait before the next cycle. After a FAILED cycle within the open-critical window, retry PROMPTLY
        (short backoff) instead of waiting the full cadence: a failure near 09:30 risks a MISSED armed entry
        (a lost court-day for the VRP proof), and sleeve opens are idempotent — broker-confirmed held_qty +
        in-flight-orders guard + book-deployment cap all prevent a double-open — so a quick retry recovers
        the entry safely. Everything else waits the normal interval. Gated (GREYLINE_OPEN_RETRY_ENABLED,
        default on); fail-safe to the normal interval on any error."""
        if not failed or (getenv("GREYLINE_OPEN_RETRY_ENABLED", "true") or "true").strip().lower() != "true":
            return interval_seconds
        try:
            from app.services.cycle_failure_forensics_engine import CycleFailureForensicsEngine
            now_et, mh = CycleFailureForensicsEngine._now_et()
            mins = CycleFailureForensicsEngine._minutes_to_open(now_et, mh)
            if mins is not None and abs(mins) <= CycleFailureForensicsEngine.NEAR_OPEN_MIN:
                backoff = int(getenv("GREYLINE_OPEN_RETRY_BACKOFF_SEC", "45") or "45")
                return max(15, min(backoff, interval_seconds))       # never longer than normal, floor 15s
        except Exception:
            pass
        return interval_seconds

    @classmethod
    def _run_loop(cls, interval_seconds):
        while not cls._stop_event.is_set():
            failed = False
            try:
                cls._run_cycle()
            except Exception as exc:
                failed = True
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
            cls._stop_event.wait(cls._next_interval(interval_seconds, failed))

    @classmethod
    def _run_cycle(cls):
        cls._load_state()
        started = datetime.utcnow().isoformat()
        cls._phase_reset()               # per-phase timing (bulletproof; see _ckpt/_phase_finalize)

        # These three run BEFORE any sleeve opens. An unguarded throw here would unwind the whole
        # cycle so NOTHING opens (the silent-open-failure class). Degrade each instead. market_hours
        # fails safe to "closed" so opens skip (and the armed-sleeve-skip watch below makes that
        # loud) rather than crash the cycle.
        try:
            market_hours = MarketHoursEngine().status()
        except Exception as exc:
            market_hours = {"is_regular_session": False, "is_open": False,
                            "status": "MARKET_HOURS_DEGRADED", "error": repr(exc)}
        try:
            token = TradeStationTokenMaintenanceEngine().evaluate()
        except Exception as exc:
            token = {"status": "TOKEN_MAINT_DEGRADED", "error": repr(exc)}
        try:
            decision = DecisionSchedulerEngine().run_manual_cycle()
        except Exception as exc:
            decision = {"status": "DECISION_CYCLE_DEGRADED", "error": repr(exc)}
        cls._ckpt("pre_mkt_token_decision")   # market-hours + TS token refresh + decision cycle

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
        try:
            forward = ForwardOutcomeCaptureEngine().capture(limit=60)
        except Exception as exc:
            forward = {"status": "FORWARD_CAPTURE_DEGRADED", "error": repr(exc)}
        try:
            learning = DecisionLearningMemoryEngine().record_current_learning()
        except Exception as exc:
            learning = {"status": "LEARNING_DEGRADED", "error": repr(exc)}

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
        cls._ckpt("pre_grade_forward_learn")  # forecast-grade + forward-capture(60) + learning + fixed-horizon

        # THROTTLE the institutional-flow pipeline (sweep + retrain) OFF the per-cycle hot path — it was
        # ~59% of cycle cost (measured 2026-08-14), is OBSERVATION_ONLY (fires no trades), and targets the
        # UNPROVEN flow edge. Run at most once/day, off-hours only. When not due, the sweep collects nothing
        # (collect flag False -> fast) and the retrain scans 0 names (limit 0 -> fast).
        _inst_due, _inst_reason = cls._institutional_pipeline_due(market_hours)
        try:
            institutional_snapshot_sweep = (
                InstitutionalSignalSnapshotSweepEngine()
                .run(
                    limit=10,
                    # Auto-on when a UW key is configured: the mission's real
                    # institutional-flow collection. No key -> stays off (no wasted budget). Resolve via
                    # the shared .env/.env.local resolver so a bare getenv can't read False (key lives in
                    # .env.local) and silently skip the mission's institutional-flow data collection.
                    # Gated OFF via GREYLINE_INSTITUTIONAL_SWEEP_ENABLED (2026-08-11 incident): this UW
                    # flow-alerts sweep (10 names) hung the cycle on a trickling chunked response body —
                    # the UW _get read-timeout is between-bytes so a stall never trips it, and the fetch
                    # isn't single-flighted (same thundering-herd class as the broker read). It's the
                    # UNPROVEN institutional-flow path, not trade-firing, so disabling it keeps the cycle
                    # alive. Re-enable once the UW provider has single-flight + a total-deadline.
                    collect_unusual_whales=_inst_due and bool(uw_api_key())
                    and (getenv("GREYLINE_INSTITUTIONAL_SWEEP_ENABLED", "true") or "true").strip().lower() == "true",
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
        cls._ckpt("pre_institutional_sweep")  # UW institutional-flow snapshot sweep (gated; known hang risk)

        try:
            institutional_retraining = (
                InstitutionalRetrainingOrchestratorEngine()
                .run(
                    limit=(10 if _inst_due else 0),   # throttled: 0 names -> near-zero cost off the hot path
                    min_age_minutes=60,
                    persist=True,
                )
            )
            if not _inst_due and isinstance(institutional_retraining, dict):
                institutional_retraining["throttled"] = _inst_reason
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
        if not _inst_due and isinstance(institutional_snapshot_sweep, dict):
            institutional_snapshot_sweep["throttled"] = _inst_reason
        elif _inst_due:
            cls._stamp_institutional_run()          # ran the full pipeline -> once/day marker
        cls._ckpt("pre_institutional_retrain")  # per-name institutional model retraining orchestrator (throttled once/day off-hours)
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
        cls._ckpt("pre_sleeve")          # RESIDUAL tail only — the heavy pre-sleeve work is now attributed
        #   across pre_mkt_token_decision / pre_grade_forward_learn / pre_institutional_sweep /
        #   pre_institutional_retrain (added 2026-08-14 to break up the 758s black box)
        from os import getenv as _getenv
        # MOMENTUM opening runs LATER (priority 5 — LOWEST, after the four edges) so the higher-
        # probability strategies claim capital first. Its EXIT manager still runs here every cycle,
        # so any open momentum positions are managed regardless of when new ones are opened.
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
        # CLOSE-side reconciliation (equity mirror of VRP reconcile_closes): upgrade quote-priced realized
        # to the actual exit fills, and REVERT any CLOSED momentum row the broker still fully holds. Runs
        # every cycle (reads broker state, places no orders) so it also heals closes made in prior cycles.
        try:
            if isinstance(momentum_exit, dict):
                momentum_exit["reconcile_closes"] = MomentumExitManagerEngine().reconcile_closes(dry_run=False)
        except Exception as exc:
            if isinstance(momentum_exit, dict):
                momentum_exit["reconcile_closes"] = {"error": repr(exc), "status": "MOMENTUM_CLOSES_RECONCILE_DEGRADED"}
        cls._ckpt("momentum_exit")

        # LEGACY ORDERLY LIQUIDATION: flatten the pre-clean-test book (legacy calls + equities) at
        # BEST price then GUARANTEED exit — re-priced against LIVE quotes each cycle, not frozen on
        # stale weekend limits. Self-terminating (no-op once those targets are gone) and gated by
        # GREYLINE_LEGACY_LIQUIDATION_ENABLED. Never touches a VRP-OS position.
        try:
            from app.services.legacy_orderly_liquidation_engine import LegacyOrderlyLiquidationEngine
            legacy_liquidation = LegacyOrderlyLiquidationEngine().run_cycle(
                is_regular_session=(market_hours.get("is_regular_session") is True))
        except Exception as exc:
            legacy_liquidation = {"error": repr(exc), "status": "LEGACY_LIQUIDATION_DEGRADED"}

        # Clean-slate reset (operator-armed via GREYLINE_FLATTEN_ALL_ENABLED). Flatten the ENTIRE
        # book to zero — shorts closed before longs, sized from the LIVE broker position — and, once
        # the book is confirmed flat, re-baseline the mission ledger to a clean $10k/0-realized line.
        # Options can't fill after hours, so this does its work at the next regular session open.
        try:
            from app.services.flatten_all_positions_engine import FlattenAllPositionsEngine
            _fa = FlattenAllPositionsEngine()
            if _fa.enabled():
                flatten_all = _fa.run_cycle(
                    is_regular_session=(market_hours.get("is_regular_session") is True))
                if flatten_all.get("status") == "FLATTEN_ALL_FLAT":
                    from app.services.account_rebaseline_engine import AccountRebaselineEngine
                    flatten_all["rebaseline"] = AccountRebaselineEngine().rebaseline_if_pending(
                        reason="operator clean-slate reset to $10k / 0 positions")
            else:
                flatten_all = {"status": "FLATTEN_ALL_DISABLED"}
        except Exception as exc:
            flatten_all = {"error": repr(exc), "status": "FLATTEN_ALL_DEGRADED"}

        # TARGETED orphan flatten (GATED by GREYLINE_ORPHAN_FLATTEN=<comma symbols>): close ONLY the named
        # positions — orphans left UNMANAGED when their sleeve was disarmed (e.g. the low_vol/xs names when
        # the book narrowed to trend-only). Reuses FlattenAll's marketable-close safety on just those
        # tickers; trend / carry / everything else is untouched. Sells-only close = allowed under the master
        # kill switch. Market-closed short-circuits before any broker read; self-terminating once flat.
        try:
            _orphans = [s.strip().upper()
                        for s in (_getenv("GREYLINE_ORPHAN_FLATTEN", "") or "").split(",") if s.strip()]
            if _orphans:
                from app.services.flatten_all_positions_engine import FlattenAllPositionsEngine
                orphan_flatten = FlattenAllPositionsEngine().run_cycle(
                    is_regular_session=(market_hours.get("is_regular_session") is True),
                    only_symbols=_orphans)
            else:
                orphan_flatten = {"status": "ORPHAN_FLATTEN_UNSET"}
        except Exception as exc:
            orphan_flatten = {"error": repr(exc), "status": "ORPHAN_FLATTEN_DEGRADED"}

        # Volatility term-structure CARRY sleeve (GATED OFF by GREYLINE_VOL_CARRY_ENABLED). The one
        # backtestable variance-premium edge: SHORT vol (long SVXY, defined-risk) ONLY in contango,
        # FLAT in backwardation, vol-targeted small. Rebalances the sleeve toward its target each
        # regular-session cycle; sizes from the LIVE broker position. Short-vol, so it never self-arms.
        try:
            from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine
            _vc = VolTermStructureCarryEngine()
            vol_carry = (_vc.run_cycle(is_regular_session=(market_hours.get("is_regular_session") is True))
                         if _vc.enabled() else {"status": "VOL_CARRY_DISABLED"})
        except Exception as exc:
            vol_carry = {"error": repr(exc), "status": "VOL_CARRY_DEGRADED"}

        # Age out raw UW snapshots past the retention window (compacting flow first).
        # Self-gates to ~once/day, so this is a no-op most cycles. Best-effort.
        try:
            from app.services.uw_snapshot_retention_engine import UWSnapshotRetentionEngine
            uw_retention = UWSnapshotRetentionEngine().prune()
        except Exception as exc:
            uw_retention = {"pruned": False, "error": repr(exc),
                            "status": "UW_RETENTION_DEGRADED"}
        # Position management runs before the opening sleeves; an unguarded throw here would abort
        # every opener below. Degrade so opens still run.
        try:
            paper_position_manager = PaperPositionManagerEngine().manage_open_positions()
        except Exception as exc:
            paper_position_manager = {"status": "PAPER_POSITION_MANAGER_DEGRADED", "error": repr(exc)}
        try:
            options_position_manager = OptionsPositionManagerEngine().manage_open_positions()
        except Exception as exc:
            options_position_manager = {"status": "OPTIONS_POSITION_MANAGER_DEGRADED", "error": repr(exc)}
        # CLOSE-side reconciliation (long-option mirror of VRP/momentum reconcile_closes): compute realized
        # from the actual SELLTOCLOSE fills, and REVERT any CLOSED option the broker still holds (the
        # NO_SIM_OPTION_POSITION-on-a-degraded-read phantom). Every cycle; reads broker state, no orders.
        try:
            if isinstance(options_position_manager, dict):
                options_position_manager["reconcile_closes"] = OptionsPositionManagerEngine().reconcile_closes(dry_run=False)
        except Exception as exc:
            if isinstance(options_position_manager, dict):
                options_position_manager["reconcile_closes"] = {"error": repr(exc), "status": "OPTIONS_CLOSES_RECONCILE_DEGRADED"}

        # GATED AUTO-APPLY of the measured allocation: at most ONCE per trading day, only while the market
        # is CLOSED (never re-budget mid-session under live sizing). No-op unless GREYLINE_ALLOC_AUTOAPPLY_
        # ENABLED. Evidence-only, capped per step, reversible. Places no orders.
        try:
            from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine
            _aa = SleeveBudgetAutoApplyEngine()
            mkt_open = bool(market_hours.get("is_regular_session"))
            sleeve_budget_autoapply = _aa.run_if_due(market_open=mkt_open)
            # RISK-PARITY de-concentration glide (gated by GREYLINE_SLEEVE_RISK_BUDGET): step an
            # over-concentrated sleeve toward floored risk-parity, once/day, market-closed. Down-only,
            # reversible. No-op unless the flag is on.
            sleeve_risk_trim = _aa.run_risk_trim_if_due(market_open=mkt_open)
        except Exception as exc:
            sleeve_budget_autoapply = {"status": "AUTOAPPLY_DEGRADED", "error": repr(exc), "ran": False}
            sleeve_risk_trim = {"status": "RISK_TRIM_DEGRADED", "error": repr(exc), "ran": False}
        cls._ckpt("options_and_autoapply")

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
                # RECONCILE recorded credit/max-loss to ACTUAL fills FIRST, so manage_positions
                # (take-profit / stop / P&L) acts on reality, not the planned limit prices or
                # not-yet-filled legs. Also flags a naked short (filled short, no filled wing).
                vrp_short_premium = {"reconcile": _sp.reconcile_fills(dry_run=False),
                                     "manage": _sp.manage_positions(dry_run=False),
                                     # CLOSE-side mirror: upgrade estimate-priced closes to actual-fill P&L,
                                     # and REVERT any CLOSED row the broker still holds (close never filled).
                                     "reconcile_closes": _sp.reconcile_closes(dry_run=False)}
                _mk = _P("app/data/options_paper_trading/.vrp_short_last_open")
                _today = datetime.utcnow().date().isoformat()
                _due = True
                try:
                    _due = _mk.read_text().strip() != _today
                except Exception:
                    _due = True
                # MarketHoursEngine is imported at module scope (top of file). A redundant local
                # import here made it a function-local name, so the earlier market_hours line
                # (MarketHoursEngine().status()) hit UnboundLocalError and FAILED EVERY CYCLE.
                if _due and market_hours.get("is_regular_session"):
                    from app.services.conditional_vrp_short_premium_engine import VARIANCE_HARVEST
                    # CATALYST-AWARE TAIL DEFENSE: don't sell fresh index premium straight into a
                    # scheduled vol event (Fed/CPI/PCE/jobs) — a known gap risk for no extra edge.
                    from app.services.catalyst_risk_overlay_engine import CatalystRiskOverlayEngine
                    _cat = CatalystRiskOverlayEngine().defer_new_premium(tickers=VARIANCE_HARVEST)
                    if _cat.get("defer"):
                        # BENIGN, SELF-CLEARING HOLD: do NOT stamp the once-per-day marker here. Stamping
                        # on a deferral burned the whole day even after the catalyst window cleared — so a
                        # single morning macro print left the armed sleeve inert until the next day. Leaving
                        # the marker unstamped lets the open path re-evaluate each RTH cycle and book the
                        # first cycle the catalyst no longer applies (the Edge-proof clock keeps ticking).
                        vrp_short_premium["open"] = {"status": "DEFERRED_CATALYST", **_cat}
                    else:
                        vrp_short_premium["open"] = _sp.open_positions(
                            names=VARIANCE_HARVEST, dry_run=False, limit=2)
                        # stamp only when the booking path actually RAN (booked, or a clean no-op /
                        # surfaced error) — never on a benign catalyst hold.
                        try:
                            _mk.parent.mkdir(parents=True, exist_ok=True); _mk.write_text(_today)
                        except Exception:
                            pass
                # ARM-HEALTH GUARD: classify today's open outcome and alert on the states that matter —
                # a booking error (armed but silently books 0) immediately, or a stalled proof clock
                # (armed but nothing booked for N sessions). Benign holds stay visible but quiet.
                try:
                    _ah = _sp.arm_health(open_outcome=vrp_short_premium.get("open"),
                                         is_rth=market_hours.get("is_regular_session"), record=True)
                    vrp_short_premium["arm_health"] = _ah
                    if _ah.get("should_alert"):
                        from app.services.external_alert_engine import ExternalAlertEngine
                        ExternalAlertEngine().dispatch(
                            title="VRP arm-health", message=_ah.get("message") or "",
                            severity=_ah.get("severity") or "WARNING",
                            fingerprint=_ah.get("fingerprint"))
                except Exception:
                    pass
        except Exception as exc:
            vrp_short_premium = {"status": "VRP_SHORT_PREMIUM_DEGRADED", "error": repr(exc)}
        cls._ckpt("vrp_short_premium")

        # Trend-following equity sleeve (PRIORITY 3, GATED OFF by GREYLINE_TREND_ENABLED). Long/flat
        # 200-DMA on a diversified ETF basket — the long-convexity diversifier. Sizes from LIVE broker.
        try:
            from app.services.trend_following_engine import TrendFollowingEngine
            _tf = TrendFollowingEngine()
            trend_following = (_tf.run_cycle(is_regular_session=(market_hours.get("is_regular_session") is True))
                               if _tf.enabled() else {"status": "TREND_DISABLED"})
        except Exception as exc:
            trend_following = {"error": repr(exc), "status": "TREND_DEGRADED"}

        # MANAGED-FUTURES / TSMOM sleeve (forward test, gated OFF): the crisis-convex diversifier.
        # run_cycle handles the monthly cadence, disabled, and unfunded (0-budget) paths internally,
        # so this is a pure no-op until GREYLINE_MANAGED_FUTURES_ENABLED + a non-zero ALLOC_PCT are set.
        try:
            from app.services.managed_futures_engine import ManagedFuturesEngine
            _mf = ManagedFuturesEngine()
            managed_futures = (_mf.run_cycle(is_regular_session=(market_hours.get("is_regular_session") is True))
                               if _mf.enabled() else {"status": "MF_DISABLED"})
        except Exception as exc:
            managed_futures = {"error": repr(exc), "status": "MF_DEGRADED"}

        # LOW-VOLATILITY / BAB sleeve (GATED OFF by GREYLINE_LOW_VOL_ENABLED) — the equity/ETF replacement
        # for the retired earnings-vol condor sleeve. Inverse-vol-weighted low-vol ETF basket, whole-share.
        try:
            from app.services.low_volatility_engine import LowVolatilityEngine
            _lv = LowVolatilityEngine()
            low_volatility = (_lv.run_cycle(is_regular_session=(market_hours.get("is_regular_session") is True))
                              if _lv.enabled() else {"status": "LOW_VOL_DISABLED"})
        except Exception as exc:
            low_volatility = {"error": repr(exc), "status": "LOW_VOL_DEGRADED"}

        # CROSS-SECTIONAL MOMENTUM (dual-momentum ETF sleeve) — the missing AQR canonical style, forward-test
        # candidate. Gated OFF; monthly cadence with prompt exit on a faded leader. /cross-sectional-momentum.
        try:
            from app.services.cross_sectional_momentum_engine import CrossSectionalMomentumEngine
            _xm = CrossSectionalMomentumEngine()
            xs_momentum = (_xm.run_cycle(is_regular_session=(market_hours.get("is_regular_session") is True))
                           if _xm.enabled() else {"status": "XSMOM_DISABLED"})
        except Exception as exc:
            xs_momentum = {"error": repr(exc), "status": "XSMOM_DEGRADED"}
        cls._ckpt("tf_mf_sleeves")     # sub-instrument the heavy block so a real cycle attributes the cost

        # OPEN-WINDOW GUARD: the 5 recomputes below are minutes-long serial UW/TS chain scans and NONE is
        # on the trade-firing path. Measured, this block is ~164 min (96% of the cycle) — long enough to
        # straddle the 09:30 open and starve the broker read (failing the exposure gate closed). So on
        # trading days they are DEFERRED from ~05:00 ET through the 16:00 close; they still run overnight
        # and post-close, which is their natural cadence. Computed once here; each step honours it.
        _heavy_blocked, _heavy_reason = cls._heavy_recompute_blocked(market_hours)

        # INTRADAY-SHADOW EXEMPTION (2026-08-25): the gex walls-fade and vanna shadows must act on LIVE intraday
        # quotes — but the _heavy_blocked defer above (built for the 164-min chain scans) spans exactly the RTH
        # hours they'd act, while overnight they run-but-MARKET_CLOSED. So under normal scheduling they could
        # never open (why gex showed 0 positions). Unlike the chain scans they are SAFE intraday: each self-gates
        # to hourly (MARK_INTERVAL_MIN=60) and fail-closes off-session (equity_session_open()), so the worst they
        # add near the open is a handful of batched TS quotes + a cached UW gamma read once an hour — it cannot
        # straddle the open or starve the broker read. Allow them through RTH by default; the escape hatch
        # GREYLINE_INTRADAY_SHADOWS_RTH=false restores the old heavy-defer if TS/UW throttling is ever observed.
        _intraday_shadow_blocked = cls._intraday_shadow_deferred(_heavy_blocked)

        # CONDOR SHADOW forward-test: record the VRP/earnings condors the sleeves would open (built off
        # UW's clean greeks+NBBO) and mark them to market off UW — the options-premium forward-test the
        # SIM sandbox can't run. NO orders. Self-gated once/day. Gated by GREYLINE_CONDOR_SHADOW.
        try:
            if _intraday_shadow_blocked:   # RTH-EXEMPT: settles at live quotes (equity_session_open) + UW read is run_if_due-throttled — was deadlocked under _heavy_blocked (0 settles)
                condor_shadow = {"status": "CONDOR_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.condor_shadow_engine import CondorShadowEngine
                condor_shadow = CondorShadowEngine().run_if_due()
        except Exception as exc:
            condor_shadow = {"error": repr(exc), "status": "CONDOR_SHADOW_DEGRADED"}
        cls._ckpt("condor_shadow")

        # OVERNIGHT-return anomaly shadow — zero-capital forward test (close->open premium on the tightest
        # index ETFs). Appends the latest not-yet-recorded overnight observation from the daily bars, once/day.
        # NO orders; reads only. Gated by GREYLINE_OVERNIGHT_SHADOW (default on — measurement only).
        try:
            from app.services.overnight_anomaly_shadow_engine import OvernightAnomalyShadowEngine
            overnight_shadow = OvernightAnomalyShadowEngine().run_if_due()
        except Exception as exc:
            overnight_shadow = {"error": repr(exc), "status": "OVERNIGHT_SHADOW_DEGRADED"}
        cls._ckpt("overnight_shadow")

        # FOMC-CYCLE equity-timing shadow — zero-capital forward test (CMVJ 2019: the equity premium concentrates
        # in EVEN FOMC-cycle weeks). Appends the latest not-yet-recorded SPY daily return + its cycle-week, once/day.
        # NO orders; reads only. Gated by GREYLINE_FOMC_CYCLE_SHADOW (default on — measurement only).
        try:
            from app.services.fomc_cycle_shadow_engine import FomcCycleShadowEngine
            fomc_cycle_shadow = FomcCycleShadowEngine().run_if_due()
        except Exception as exc:
            fomc_cycle_shadow = {"error": repr(exc), "status": "FOMC_CYCLE_SHADOW_DEGRADED"}
        cls._ckpt("fomc_cycle_shadow")

        # OPTION-IMPLIED SKEW shadow — zero-capital market-neutral forward test (25d risk reversal predicts the
        # stock; Xing-Zhang-Zhao / Cremers-Weinbaum). Weekly top-K-long / bottom-K-short cohort, settled at live
        # equity quotes. NO orders/budget. Gated by GREYLINE_IV_SKEW_SHADOW (default on — measurement only).
        if _intraday_shadow_blocked:   # RTH-EXEMPT: settles at live quotes (equity_session_open); UW read is @ttl_cached(30) — was deadlocked under _heavy_blocked (0 settles)
            iv_skew_shadow = {"status": "IV_SKEW_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
        else:
            try:
                from app.services.iv_skew_shadow_engine import IvSkewShadowEngine
                iv_skew_shadow = IvSkewShadowEngine().mark()
            except Exception as exc:
                iv_skew_shadow = {"error": repr(exc), "status": "IV_SKEW_SHADOW_DEGRADED"}
        cls._ckpt("iv_skew_shadow")

        # DISPERSION / correlation-risk-premium shadow — zero-capital forward test (short index vol / long single-
        # name vol; harvest implied-minus-realized correlation). Monthly cohort off UW IVs + realized bars. NO
        # orders/budget. Gated by GREYLINE_DISPERSION_SHADOW (default on — measurement only).
        if _intraday_shadow_blocked:   # RTH-EXEMPT: settles at live quotes (equity_session_open); UW read is @ttl_cached(30) — was deadlocked under _heavy_blocked (0 settles)
            dispersion_shadow = {"status": "DISPERSION_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
        else:
            try:
                from app.services.dispersion_shadow_engine import DispersionShadowEngine
                dispersion_shadow = DispersionShadowEngine().mark()
            except Exception as exc:
                dispersion_shadow = {"error": repr(exc), "status": "DISPERSION_SHADOW_DEGRADED"}
        cls._ckpt("dispersion_shadow")

        # Record the daily gamma_flip-vs-spot gap for the condor proxies (UW serves flip live-only) so GATE 2's
        # regime can be TRENDED — CONVERGING (warming) vs DIVERGING. Reuses the same 900s-cached _gex_map the
        # shadow just read; one row/symbol/day; read-only, isolated so it can't disturb the cycle.
        try:
            from app.services.gamma_flip_history_engine import GammaFlipHistoryEngine
            gamma_flip_history = GammaFlipHistoryEngine().record()
        except Exception as exc:
            gamma_flip_history = {"error": repr(exc), "status": "GAMMA_FLIP_HISTORY_DEGRADED"}
        cls._ckpt("gamma_flip_history")

        # Extended-ETF SHADOW — zero-capital cross-sectional-momentum forward-test on the 52-ETF universe
        # (the measurement layer that lets a scanned ETF earn its way toward a verdict). NO orders/budget.
        # RTH-EXEMPT (2026-09-04): it settles/opens at LIVE quotes so it can ONLY act during the regular
        # session (equity_session_open) — but the full _heavy_blocked defer spans exactly that window, so it
        # could only ever run overnight, when the tradeability gate fail-closes it. That deadlock froze the
        # 08-12 cohort unsettled for 3wk with 0/8 cohorts (identical to the gex "0 positions" bug). mark() is
        # light (rank 52 ETFs off disk + a few batched quotes only when it actually settles/opens), so gate it
        # on the intraday exemption like gex/vanna, NOT the heavy-chain defer.
        try:
            if _intraday_shadow_blocked:
                extended_etf_shadow = {"status": "ETF_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
            else:
                from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine
                extended_etf_shadow = ExtendedEtfShadowEngine().mark()
        except Exception as exc:
            extended_etf_shadow = {"error": repr(exc), "status": "ETF_SHADOW_DEGRADED"}
        cls._ckpt("extended_etf_shadow")

        # Long-vol ETP SHADOW — the regime-conditioned long-vol leg (long VXX only in backwardation),
        # complements the SVXY short-vol carry sleeve. Zero capital, NO orders.
        try:
            if _intraday_shadow_blocked:   # RTH-EXEMPT: settles at live quotes (equity_session_open); light (VXX quotes only) — was deadlocked under _heavy_blocked (0 settles)
                vol_etp_shadow = {"status": "VOL_ETP_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
            else:
                from app.services.vol_etp_shadow_engine import VolEtpShadowEngine
                vol_etp_shadow = VolEtpShadowEngine().mark()
        except Exception as exc:
            vol_etp_shadow = {"error": repr(exc), "status": "VOL_ETP_SHADOW_DEGRADED"}
        cls._ckpt("vol_etp_shadow")

        # Futures TSMOM shadow — the REAL managed-futures test (vs ETF proxies). Keep the alt-asset bars
        # fresh (once/day, append-only) so the 12-month signal stays current, then mark the shadow. NO orders.
        try:
            if _heavy_blocked:
                futures_tsmom_shadow = {"status": "FUT_TSMOM_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
            else:
                from app.services.alt_asset_universe_engine import AltAssetUniverseEngine
                AltAssetUniverseEngine.refresh_if_due()
                from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine
                futures_tsmom_shadow = FuturesTsmomShadowEngine().mark()
        except Exception as exc:
            futures_tsmom_shadow = {"error": repr(exc), "status": "FUT_TSMOM_SHADOW_DEGRADED"}
        cls._ckpt("futures_tsmom_shadow")

        # FX trend shadow — completes the alt-asset measurement trio (spot FX). NO orders/budget.
        try:
            if _heavy_blocked:
                fx_trend_shadow = {"status": "FX_TREND_SHADOW_DEFERRED_OPEN_WINDOW", "acted": False, "reason": _heavy_reason}
            else:
                from app.services.fx_trend_shadow_engine import FxTrendShadowEngine
                fx_trend_shadow = FxTrendShadowEngine().mark()
        except Exception as exc:
            fx_trend_shadow = {"error": repr(exc), "status": "FX_TREND_SHADOW_DEGRADED"}
        cls._ckpt("fx_trend_shadow")

        # GEX MEAN-REVERSION shadow — a NEW strategy (fade the walls toward the gamma-magnet in long-gamma
        # pinning regimes), forward-tested on the underlying with NO orders. Same heavy-window gate.
        try:
            if _intraday_shadow_blocked:
                gex_strategy_shadow = {"status": "GEX_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.gex_mean_reversion_shadow_engine import GexMeanReversionShadowEngine
                gex_strategy_shadow = GexMeanReversionShadowEngine().mark()
        except Exception as exc:
            gex_strategy_shadow = {"error": repr(exc), "status": "GEX_SHADOW_DEGRADED"}
        cls._ckpt("gex_strategy_shadow")

        # VANNA/CHARM shadow — the 'vanna rally into OPEX' (2nd-order dealer flow), forward-tested LONG the
        # index in the OPEX window on a negative-vanna setup. NO orders. Same heavy-window gate.
        try:
            if _intraday_shadow_blocked:
                vanna_charm_shadow = {"status": "VANNA_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.vanna_charm_shadow_engine import VannaCharmShadowEngine
                vanna_charm_shadow = VannaCharmShadowEngine().mark()
        except Exception as exc:
            vanna_charm_shadow = {"error": repr(exc), "status": "VANNA_SHADOW_DEGRADED"}
        cls._ckpt("vanna_charm_shadow")

        # SHADOW MARK HEARTBEAT — persist a cadence-independent 'last actually ran' per shadow so a silent
        # multi-day stall (the 08-16 process peg / 08-17 freeze class) becomes a LOUD reality-guard banner line
        # instead of being caught by chance. `last_ran` advances only for shadows that truly executed this cycle
        # (deferred/disabled/errored ones don't refresh it). Bulletproof — a monitoring write can't break the cycle.
        try:
            from app.services.shadow_mark_heartbeat import record as _record_shadow_heartbeats
            _record_shadow_heartbeats({
                "condor": condor_shadow, "overnight": overnight_shadow, "fomc_cycle": fomc_cycle_shadow,
                "iv_skew": iv_skew_shadow, "dispersion": dispersion_shadow, "extended_etf": extended_etf_shadow,
                "vol_etp": vol_etp_shadow, "futures_tsmom": futures_tsmom_shadow, "fx_trend": fx_trend_shadow,
                "gex_strategy": gex_strategy_shadow, "vanna_charm": vanna_charm_shadow,
            })
        except Exception:
            pass
        cls._ckpt("shadow_heartbeats")

        # OPTIONABLE UNIVERSE: derive the VRP/condor candidate universe from live option open interest
        # (UW /screener/stocks) instead of a hand-typed list. Re-screens ONCE PER TRADING DAY at the
        # 16:00 ET close (settled data) so it never goes stale; bootstraps immediately if unset. Fail-safe
        # (a broken screen keeps the last good cache; VRP falls back to the curated list if none exists).
        try:
            if _heavy_blocked:
                optionable_universe = {"status": "OPTIONABLE_UNIVERSE_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.optionable_universe_engine import OptionableUniverseEngine
                optionable_universe = OptionableUniverseEngine().recompute_if_due(market_hours)
        except Exception as exc:
            optionable_universe = {"error": repr(exc), "status": "OPTIONABLE_UNIVERSE_DEGRADED"}
        cls._ckpt("optionable_universe")

        # MOMENTUM SCAN WARM: once/day live universe scan so the equity shadow can open weekly cohorts on
        # a FRESH live signal (the shadow never triggers this heavy ~5-min TS fetch itself). Same heavy-
        # window gate as the universe/condor refreshes → runs overnight/post-close. Gated OFF by default.
        try:
            if _heavy_blocked:
                momentum_scan_warm = {"status": "MOM_SCAN_WARM_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.momentum_scan_warm_engine import MomentumScanWarmEngine
                momentum_scan_warm = MomentumScanWarmEngine().warm_if_due(market_hours)
        except Exception as exc:
            momentum_scan_warm = {"error": repr(exc), "status": "MOM_SCAN_WARM_DEGRADED"}
        cls._ckpt("momentum_scan_warm")

        # SECTOR MAP: keep the concentration-cap's sector buckets current with the drifting traded
        # universe — same once-per-day post-close gate as the optionable universe. Stocks are data-derived
        # from UW; ETFs stay in the exposure engine's deliberate literal map. Unmapped traded names are
        # recorded (loud, not silent).
        try:
            if _heavy_blocked:
                sector_map_refresh = {"status": "SECTOR_MAP_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.sector_map_engine import SectorMapEngine
                sector_map_refresh = SectorMapEngine().recompute_if_due(market_hours)
        except Exception as exc:
            sector_map_refresh = {"error": repr(exc), "status": "SECTOR_MAP_DEGRADED"}
        cls._ckpt("sector_map")

        # BEST-CONDORS list for the dashboard: recompute the ranked buildable condors (off UW) at most
        # once/10min and cache to a file, so the /best-condors route (dashboard card) is always instant.
        # This is the ONE step whose 10-min TTL makes it recompute EVERY cycle — the dominant open-window
        # offender — so the guard matters most here; the card serves its last (pre-open) computation with
        # an age badge meanwhile.
        try:
            # Both condor sleeves (VRP + earnings-vol) are RETIRED and the dashboard card was removed, so
            # this per-cycle UW recompute (the dominant open-window offender) is dead work by default. Gate
            # it OFF; re-enable with GREYLINE_BEST_CONDORS_ENABLED=true if condors ever come back.
            if (getenv("GREYLINE_BEST_CONDORS_ENABLED", "") or "").strip().lower() != "true":
                best_condors = {"status": "BEST_CONDORS_DISABLED", "ran": False,
                                "reason": "condor sleeves retired — recompute gated off"}
            elif _heavy_blocked:
                best_condors = {"status": "BEST_CONDORS_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.best_condors_engine import BestCondorsEngine
                best_condors = BestCondorsEngine().recompute_if_due()
        except Exception as exc:
            best_condors = {"error": repr(exc), "status": "BEST_CONDORS_DEGRADED"}
        cls._ckpt("best_condors")

        # MF SHADOW forward-test: mark the FULL long/short strategy's hypothetical P&L on settled bars
        # (NO orders). Runs regardless of the live sleeve — it's how the real diversification edge
        # accumulates while the sleeve is parked. Self-gated to once per new settled bar.
        try:
            if _heavy_blocked:
                managed_futures_shadow = {"status": "MF_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.managed_futures_shadow_engine import ManagedFuturesShadowEngine
                managed_futures_shadow = ManagedFuturesShadowEngine().mark()
        except Exception as exc:
            managed_futures_shadow = {"error": repr(exc), "status": "MF_SHADOW_DEGRADED"}
        # CROSS-SECTIONAL MOMENTUM shadow — accumulate the dual-momentum edge on paper (NO orders) while
        # the live sleeve is parked on the sleeve-position collision. Once/settled-bar. /cross-sectional-momentum-shadow.
        try:
            if _heavy_blocked:
                xs_momentum_shadow = {"status": "XSMOM_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.cross_sectional_momentum_shadow_engine import CrossSectionalMomentumShadowEngine
                xs_momentum_shadow = CrossSectionalMomentumShadowEngine().mark()
        except Exception as exc:
            xs_momentum_shadow = {"error": repr(exc), "status": "XSMOM_SHADOW_DEGRADED"}
        # MOMENTUM-REVERSAL EQUITY shadow — measure the true (un-survivorship-biased) equity factor edge on
        # paper (NO orders, NO budget) while the sleeve is parked, so we learn if it survives live before
        # committing capital. Weekly non-overlapping cohorts on settled bars. /momentum-equity-shadow.
        try:
            if _intraday_shadow_blocked:   # RTH-EXEMPT: settles at live quotes (equity_session_open); light (equity quotes on settle/open only) — was deadlocked under _heavy_blocked (0 settles)
                momentum_equity_shadow = {"status": "MOM_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine
                momentum_equity_shadow = MomentumReversalShadowEngine().mark()
        except Exception as exc:
            momentum_equity_shadow = {"error": repr(exc), "status": "MOM_SHADOW_DEGRADED"}
        # LOW-VOL (BAB) EQUITY shadow — measure the parked low-vol basket's edge on paper (NO orders, NO
        # budget), settled-bar daily marking with the sleeve's own inverse-vol weights. /low-volatility-shadow.
        try:
            if _heavy_blocked:
                low_vol_shadow = {"status": "LOWVOL_SHADOW_DEFERRED_OPEN_WINDOW", "ran": False, "reason": _heavy_reason}
            else:
                from app.services.low_volatility_shadow_engine import LowVolatilityShadowEngine
                low_vol_shadow = LowVolatilityShadowEngine().mark()
        except Exception as exc:
            low_vol_shadow = {"error": repr(exc), "status": "LOWVOL_SHADOW_DEGRADED"}
        cls._ckpt("mf_shadow")
        cls._ckpt("trend_mf_carry")    # terminal marker kept (≈0 now) so existing consumers of the label still resolve

        # EARNINGS-VOL harvest (forward test, gated): sell a tiny defined-risk condor into a rich-IV
        # name's earnings, once/day, RTH only. Positions land in the VRP ledger with strategy tag, so
        # the reconcile+manage above and the protective-stop/dashboard machinery already cover them.
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            _ev2 = EarningsVolHarvestEngine()
            if not _ev2.enabled():
                earnings_vol_harvest = {"status": "EARNINGS_VOL_DISABLED"}
            else:
                _evmk = Path("app/data/options_paper_trading/.earnings_vol_last_open")
                _evtoday = datetime.utcnow().date().isoformat()
                try:
                    _evdue = _evmk.read_text().strip() != _evtoday
                except Exception:
                    _evdue = True
                if _evdue and market_hours.get("is_regular_session"):
                    # defer around imminent MACRO events (FOMC/CPI/PCE) too, so the earnings-crush
                    # evidence isn't contaminated by a macro move layered on the single-name report.
                    from app.services.catalyst_risk_overlay_engine import CatalystRiskOverlayEngine
                    _evc = [c["ticker"] for c in _ev2._candidates()]
                    _evcat = CatalystRiskOverlayEngine().defer_new_premium(tickers=_evc) if _evc else {"defer": False}
                    if _evcat.get("defer"):
                        earnings_vol_harvest = {"open": {"status": "DEFERRED_CATALYST", **_evcat}}
                    else:
                        earnings_vol_harvest = {"open": _ev2.open_positions(dry_run=False)}
                    try:
                        _evmk.parent.mkdir(parents=True, exist_ok=True); _evmk.write_text(_evtoday)
                    except Exception:
                        pass
                else:
                    earnings_vol_harvest = {"status": "EARNINGS_VOL_NOT_DUE_OR_CLOSED"}
        except Exception as exc:
            earnings_vol_harvest = {"status": "EARNINGS_VOL_HARVEST_DEGRADED", "error": repr(exc)}
        cls._ckpt("earnings_vol")

        # MOMENTUM opening (PRIORITY 5 — LOWEST). Directional momentum OPENS positions; deployed here,
        # AFTER the four edges, so the higher-probability strategies claim capital first. It is the
        # strategy that lost 41% with no proven edge — operator-enabled; kill with GREYLINE_MOMENTUM_ENABLED=false.
        momentum_on = (_getenv("GREYLINE_MOMENTUM_ENABLED", "true") or "true").lower() == "true"
        options_mode = (_getenv("GREYLINE_OPTIONS_MODE", "") or "").lower() == "true"
        if not momentum_on:
            momentum_reversal = {"placed_count": 0, "rebalanced": False,
                                 "status": "MOMENTUM_DISABLED_CLEAN_VRP_TEST"}
        elif options_mode:
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

        # T-BILL CASH SWEEP (runs LAST): park the idle mission remainder in SGOV so it earns instead of
        # sitting dead. Because it runs after every strategy has claimed its capital, it sweeps only what
        # is genuinely idle. GATED by GREYLINE_TBILL_SWEEP_ENABLED; RTH only (SGOV is an equity).
        try:
            from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
            _ts = TbillCashSweepEngine()
            if not _ts.enabled():
                tbill_sweep = {"status": "TBILL_SWEEP_DISABLED"}
            elif market_hours.get("is_regular_session") is True:
                tbill_sweep = _ts.sweep(dry_run=False)
            else:
                tbill_sweep = {"status": "TBILL_SWEEP_MARKET_CLOSED"}
        except Exception as exc:
            tbill_sweep = {"error": repr(exc), "status": "TBILL_SWEEP_DEGRADED"}

        # MISSION RISK GOVERNOR (monitor-only, additive): after all deployment, watch the BOOK as a
        # whole — daily loss ladder (warn/halt-alert) and total-deployment cap — and SCREAM via iMessage
        # on a breach. Read-only on the trading path; it never halts or trades, only alerts.
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            risk_governor = MissionRiskGovernorEngine().check_and_alert()
        except Exception as exc:
            risk_governor = {"error": repr(exc), "status": "MISSION_RISK_GOVERNOR_DEGRADED"}
        cls._ckpt("ps_momentum")     # sub-instrument post_sleeve (now the cycle's #1)

        # EDGE PERSISTENCE (Medallion discipline, additive read-only): record today's per-sleeve marks
        # so each strategy builds a LIVE track record — the foundation for retiring decayed sleeves on
        # evidence. Overwrites today's row each cycle, so it ends the day on the latest marks.
        # FILL-CONFIRM sleeve closes BEFORE the court reads them: upgrade quote_estimate exits to the real
        # broker fill while it is still in the order window, so the court judges REAL fills, not marks. Runs
        # every cycle, idempotent, fail-closed — never places an order. (2026-08-08)
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            sleeve_fill_confirm = SleeveTradeLedgerEngine().upgrade_close_fills()
        except Exception as exc:
            sleeve_fill_confirm = {"error": repr(exc), "status": "SLEEVE_FILLS_DEGRADED"}

        # In-cycle readiness + reality-guard force-refresh. GATED OFF by default (2026-08-11): these add
        # ~50 TS/UW SSL reads to the cycle, and under concurrent dashboard-poll load one can HANG on a
        # socket read with no effective timeout and FREEZE the whole cycle (confirmed via process sampling
        # — cycle_count stuck; the routes still serve their lazily-populated caches, so trading loses nothing
        # by skipping this). Re-enable only once every TS/UW call on this path is hard-timeout-bounded so a
        # hung read cannot block the cycle. Flag: GREYLINE_SCHEDULER_INLINE_GUARDS.
        if (getenv("GREYLINE_SCHEDULER_INLINE_GUARDS", "false") or "false").strip().lower() == "true":
            try:
                from app.services.pre_open_readiness_engine import (
                    PreOpenReadinessEngine, _AUDIT_CACHE, _audit_ttl)
                import time as _t
                _age = _t.monotonic() - _AUDIT_CACHE["at"]
                if _AUDIT_CACHE["result"] is None or _age >= _audit_ttl():
                    PreOpenReadinessEngine().audit(allow_cache=False)
            except Exception:
                pass
            try:
                from app.services.greyline_reality_guard_engine import (
                    GreyLineRealityGuardEngine, _GUARD_CACHE, _guard_ttl)
                import time as _t2
                _gage = _t2.monotonic() - _GUARD_CACHE["at"]
                _rg = GreyLineRealityGuardEngine()
                if _GUARD_CACHE["result"] is None or _gage >= _guard_ttl():
                    _rg.check(allow_cache=False)
                reality_guard_alert = _rg.fantasy_alert()
            except Exception as exc:
                reality_guard_alert = {"error": repr(exc), "status": "REALITY_GUARD_ALERT_DEGRADED"}

        try:
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            _epe = EdgePersistenceEngine()
            edge_persistence = _epe.snapshot()
            edge_persistence["fill_confirm"] = sleeve_fill_confirm
            # RETIRE half of the discipline: page (deduped) if the court judged any sleeve DECAYED.
            edge_persistence["decay_alert"] = _epe.decay_alert()
            # WIN half: page ONCE as a sleeve crosses each proof milestone (first close / gate reached / PROVEN)
            # — the alert the confirmed-but-unproven VRP harvest most needs as its condors start closing.
            edge_persistence["proof_milestone_alert"] = _epe.proof_milestone_alert()
            # REALLOCATE half: page (deduped) when a measured verdict drifts the evidence-based
            # allocation materially from the live budget — i.e. it's time to approve a re-alloc.
            from app.services.capital_allocator_engine import CapitalAllocatorEngine
            edge_persistence["alloc_drift_alert"] = CapitalAllocatorEngine().drift_alert()
        except Exception as exc:
            edge_persistence = {"error": repr(exc), "status": "EDGE_PERSISTENCE_DEGRADED"}

        # PRE-REGISTERED edge-proof protocol: freeze each sleeve's hypothesis + required N + kill-rule
        # (bootstrap is idempotent — never overwrites a frozen protocol) and render the BINDING verdict
        # against the court above. Evidence-only; the operator's hope doesn't get a vote. /edge-proof-protocol.
        try:
            from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine
            _epp = EdgeProofProtocolEngine()
            _epp.bootstrap()
            edge_proof = _epp.evaluate()
        except Exception as exc:
            edge_proof = {"error": repr(exc), "status": "EDGE_PROOF_PROTOCOL_DEGRADED"}

        # FIRST REAL CLOSE watch: page the operator the MOMENT any sleeve books its first NON-FORCED
        # (strategy-logic) exit — the milestone that starts real edge accumulation. GreyLine has never
        # closed a trade on its own logic (all forced flattens); this makes that first one unmissable.
        # Idempotent (permanent per-sleeve marker); reads the court above, never recomputes. /edge-first-close.
        try:
            from app.services.edge_first_close_watch_engine import EdgeFirstCloseWatchEngine
            edge_first_close = EdgeFirstCloseWatchEngine().run_cycle()
        except Exception as exc:
            edge_first_close = {"error": repr(exc), "status": "EDGE_FIRST_CLOSE_DEGRADED"}

        # BOOK GREEKS: keep the harvest a PURE vol bet, not an accidental directional one. Computes
        # the aggregate delta and, if delta-hedging is armed, trades the underlying to neutralise it.
        # Cheap when flat (returns immediately with no open legs); only fetches chains when positions
        # exist. Reports the recommended hedge either way.
        try:
            from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
            _pg = PortfolioGreeksEngine()
            bg = _pg.book_greeks()
            book_greeks = {"net_delta_shares": bg.get("net_delta_shares"), "net_vega": bg.get("net_vega"),
                           "delta_neutral": bg.get("delta_neutral"), "open_legs": bg.get("open_legs")}
            if bg.get("delta_hedge") and _pg._hedge_enabled():
                book_greeks["hedge"] = _pg.hedge_delta(dry_run=False)
            elif bg.get("delta_hedge"):
                book_greeks["hedge_recommended"] = bg["delta_hedge"]
        except Exception as exc:
            book_greeks = {"status": "BOOK_GREEKS_DEGRADED", "error": repr(exc)}

        # MISSION REALIZED P&L: keep a cumulative, honest record of closed-trade P&L so a realized
        # loss can't vanish from the equity (the broker's daily realized resets at midnight). Backfill
        # the pre-tracking legacy flatten once, then book the broker's daily-realized delta each cycle.
        try:
            from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
            _mr = MissionRealizedPnlEngine()
            _mr.ensure_legacy_backfill()
            mission_realized = _mr.record_from_broker()
        except Exception as exc:
            mission_realized = {"status": "MISSION_REALIZED_DEGRADED", "error": repr(exc)}

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

        cls._ckpt("ps_edge_greeks_reconcilers")   # edge snapshots + book-greeks + mission-pnl + 3 reconcilers

        # DATA AUTO-REMEDIATION (self-gates once/day): the missing piece that used to need a manual
        # script. Appends stale bars from TradeStation (append-only — never the Yahoo full-backfill),
        # repairs OHLC violations (clamp only, backed up), and re-accepts lineage ONLY on a clean
        # restatement (no changed symbol also integrity-critical) — else it holds + alerts. Refresh
        # fixes DATA_FRESHNESS/REGIME_GATE (they read the CSVs directly) the same cycle. Runs after the
        # validators so it acts on their freshest reports. Gated by GREYLINE_DATA_AUTOREMEDIATE.
        try:
            from app.services.data_remediation_engine import DataRemediationEngine
            _dre = DataRemediationEngine()
            data_remediation = _dre.run_if_due()
            # EVENT-DRIVEN: this cycle just ran verify/scan above; if they flagged a NEW data fault,
            # remediate NOW rather than waiting for tomorrow's daily pass (the daily run can fire before
            # the day's scan identifies the fault). Throttled + fingerprint-deduped inside run_on_alert
            # so it can never hammer the TS API on a persistent fault. Skip if the daily run already ran.
            if not data_remediation.get("ran"):
                data_remediation["on_alert"] = _dre.run_on_alert()
        except Exception as exc:
            data_remediation = {"status": "DATA_REMEDIATION_DEGRADED", "error": repr(exc)}
        cls._ckpt("ps_data_remediation")   # daily TS stale-bar append + OHLC repair (network; self-gated)

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
        cls._ckpt("ps_reality_capture")    # options + earnings implied-vol forward panels (record-if-due)

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
            # ATOMIC + ASYNC: runs off the cycle's critical path (a slow iCloud copy no longer
            # blocks the scheduler), builds in staging and promotes with a rename, and SCREAMS from
            # its own worker if it ends incomplete. An interrupted run can't corrupt the last good
            # backup or advance the marker onto a partial.
            backup = _dr.backup_async() if _due else {"status": "BACKUP_NOT_DUE"}
        except Exception as exc:
            backup = {"status": "BACKUP_DEGRADED", "error": repr(exc)}
        # Independent of any backup() call: scream if the MARKER is stale (a backup killed mid-run by
        # a restart/sleep never updates it, so no completion alert ever fires). Throttled.
        try:
            _dr.alert_if_stale()
        except Exception:
            pass
        # GIT off-machine backup of the unrecoverable data — the ONLY off-machine channel the service
        # can actually use (macOS TCC sandboxes this LaunchAgent from iCloud AND external volumes, so
        # DisasterRecoveryEngine's filesystem backup silently fails from here; a network git push does
        # not). Self-gated (~12h); best-effort.
        try:
            from app.services.git_data_backup_engine import GitDataBackupEngine
            git_backup = GitDataBackupEngine().run_if_due()
        except Exception as exc:
            git_backup = {"status": "GIT_DATA_BACKUP_DEGRADED", "error": repr(exc)}

        # RESTORE DRILL: prove the off-machine backup is actually RESTORABLE (present + non-empty +
        # parses), not just written. Self-gated (~weekly); screams CRITICAL if a restore would fail.
        # A backup you never test-restore is the classic latent DR failure. /disaster-restore-drill.
        try:
            from app.services.disaster_restore_drill_engine import DisasterRestoreDrillEngine
            restore_drill = DisasterRestoreDrillEngine().run_if_due()
        except Exception as exc:
            restore_drill = {"status": "RESTORE_DRILL_DEGRADED", "error": repr(exc)}

        # OFF-BOX DEADMAN heartbeat: push a tiny liveness beacon to GitHub (~every 5 min). A scheduled
        # GitHub Action fails + emails the operator if it goes stale — the only alert that survives THIS
        # Mac dying (every other channel sends FROM this Mac). /deadman-heartbeat.
        try:
            from app.services.deadman_heartbeat_engine import DeadmanHeartbeatEngine
            deadman_heartbeat = DeadmanHeartbeatEngine().push_if_due()
        except Exception as exc:
            deadman_heartbeat = {"status": "DEADMAN_HEARTBEAT_DEGRADED", "error": repr(exc)}
        cls._ckpt("ps_backups_dr")         # DR backup(async)+git push+restore drill+deadman (all self-gated 12-20h)

        # Broker-side disaster stops: the only protection that survives THIS process dying.
        # Every doctrine exit (ATR stop, TP ladder, maturity liquidation) needs the scheduler
        # alive; a resting GTC stop at the broker does not. Default OFF, and each cycle it only
        # covers positions that lack a working sell (never stacks on a close — double-sell guard).
        try:
            from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
            _bp = BrokerProtectiveStopEngine()
            broker_stops = _bp.ensure_stops() if _bp.enabled() else _bp.status()
            # FIRE DRILL: read-only, ~12h — verify the armed stops are actually resting at the broker with
            # FULL-quantity coverage per position (a partial-qty stop passes the coarse check but leaves
            # risk). Screams CRITICAL on a gap. Never places/cancels orders. /broker-stops-fire-drill.
            broker_stops_fire_drill = _bp.fire_drill_if_due()
        except Exception as exc:
            broker_stops = {"status": "BROKER_STOPS_DEGRADED", "error": repr(exc)}
            broker_stops_fire_drill = {"status": "BROKER_STOPS_DRILL_DEGRADED", "error": repr(exc)}
        cls._ckpt("ps_broker_stops")       # ensure resting broker stops + ~12h fire drill (broker read/quotes)

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
        # DAILY-GATED (2026-08-14): tradability is a slow-moving property (new bars arrive daily), so the
        # full-bar scan does not need to run every 5-min cycle — it was part of the ~273s per-cycle baseline
        # of this post-trade phase. Runs at most once/UTC-day; consumers read the saved result meanwhile.
        _trad_marker = "app/data/scheduler/.tradability_scan_last_run"
        try:
            if cls._day_marker_due(_trad_marker):
                from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
                tradability = PriceBarTradabilityEngine().scan()
                cls._day_marker_stamp(_trad_marker)
            else:
                tradability = {"status": "TRADABILITY_SCAN_NOT_DUE", "ran": False}
        except Exception as exc:
            tradability = {"status": "TRADABILITY_SCAN_DEGRADED", "error": repr(exc)}

        # Survivorship: record today's universe point-in-time and RETAIN any symbol whose
        # feed goes quiet. Delisted-company prices can't be bought back later — TradeStation
        # purges them — so the only way to own a survivorship-free dataset is to stop
        # discarding names as they die, starting now.
        # DAILY-GATED (2026-08-14): a survivorship snapshot is by definition ONE point-in-time record per
        # day — running it every 5-min cycle just rewrote the same row and was part of this phase's per-cycle
        # baseline. Once/UTC-day. Fail-open + stamp-after-success so a missed day (permanent data loss) can't
        # happen from a marker glitch or a transient error.
        _surv_marker = "app/data/scheduler/.survivorship_last_run"
        try:
            if cls._day_marker_due(_surv_marker):
                from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine
                _surv = UniverseSurvivorshipEngine()
                survivorship = _surv.snapshot()
                survivorship["departures"] = _surv.detect_departures()
                cls._day_marker_stamp(_surv_marker)
            else:
                survivorship = {"status": "SURVIVORSHIP_ARCHIVE_NOT_DUE", "ran": False}
        except Exception as exc:
            survivorship = {"status": "SURVIVORSHIP_ARCHIVE_DEGRADED", "error": repr(exc)}

        # TOTAL-RETURN COVERAGE self-maintenance (2026-08-18): the armed GREYLINE_MOMENTUM_TOTAL_RETURN
        # signal reads adj_close; a universe expansion that outpaces the total-return build would silently
        # drop new names back to price-only (ex-div false reversals). Build a capped batch of any
        # uncovered-eligible names once/day, market CLOSED (UW load off the trading path). Day-gated +
        # stamp-after so a marker glitch just retries next day. Best-effort — never affects trading.
        _tr_marker = "app/data/scheduler/.total_return_coverage_last_run"
        try:
            if not bool(market_hours.get("is_regular_session")) and cls._day_marker_due(_tr_marker):
                from app.services.total_return_series_engine import TotalReturnSeriesEngine
                total_return_coverage = TotalReturnSeriesEngine().build_missing(limit=60)
                cls._day_marker_stamp(_tr_marker)
            else:
                total_return_coverage = {"status": "TR_COVERAGE_NOT_DUE", "ran": False}
        except Exception as exc:
            total_return_coverage = {"status": "TR_COVERAGE_DEGRADED", "error": repr(exc)}
        cls._ckpt("ps_integrity_scans")    # cross-source reconcile (daily) + tradability scan + survivorship (EVERY cycle — suspects)
        # Wrapped like every other step: this runs AFTER all trading, but an unguarded throw here
        # would abort before _record_result("COMPLETE"), falsely marking a successful cycle FAILED
        # (and could trip the 3-strike off-box alert). Degrade instead.
        try:
            from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
            health = SystemHealthDashboardEngine().status()
        except Exception as exc:
            health = {"status": "SYSTEM_HEALTH_DASHBOARD_DEGRADED", "error": repr(exc)}

        # Scheduled operator self-reports: pre-open readiness pager (~9:25 ET) and post-close summary
        # (~16:05 ET), once/day, texted off-box. So knowing the open fired cleanly never depends on a
        # human checking. Best-effort; runs after all trading; can never affect it.
        try:
            from app.services.scheduled_operator_reports_engine import ScheduledOperatorReportsEngine
            scheduled_reports = ScheduledOperatorReportsEngine.run(market_hours)
        except Exception as exc:
            scheduled_reports = {"status": "SCHEDULED_REPORTS_DEGRADED", "error": repr(exc)}
        cls._ckpt("ps_remediation_backup_health")   # RESIDUAL: system-health dashboard + scheduled operator reports
        #   (the heavy work is now attributed across ps_data_remediation / ps_reality_capture / ps_backups_dr /
        #    ps_broker_stops / ps_integrity_scans — added 2026-08-14 to break up the ~800s black box)
        cls._ckpt("post_sleeve")         # terminal marker kept (≈0 now) so existing consumers of the label resolve
        cls._phase_finalize()            # -> cls._last_phase_timings for /background-scheduler/status

        cls._cycle_count += 1
        cls._last_run = started
        cls._last_status = "BACKGROUND_SCHEDULER_CYCLE_COMPLETE"
        cls._record_result("COMPLETE", started)

        # #3: a COMPLETE cycle can still hide an armed sleeve that silently faulted. Alert on that.
        def _st(r):
            return r.get("status") if isinstance(r, dict) else None
        cls._watch_armed_sleeve_faults(market_hours, {
            "decision": _st(decision), "token": _st(token), "forward": _st(forward),
            "learning": _st(learning), "paper_position_manager": _st(paper_position_manager),
            "options_position_manager": _st(options_position_manager), "market_hours": _st(market_hours),
            "vol_carry": _st(vol_carry), "trend_following": _st(trend_following),
            "managed_futures": _st(managed_futures),
            "tbill_sweep": _st(tbill_sweep), "momentum_reversal": _st(momentum_reversal),
            "momentum_exit": _st(momentum_exit), "earnings_vol_harvest": _st(earnings_vol_harvest),
            "vrp_short_premium": _st(vrp_short_premium), "broker_stops": _st(broker_stops),
        })
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
                "vol_carry_status": vol_carry.get("status"),
                "trend_following_status": trend_following.get("status"),
                "trend_assets_in_uptrend": trend_following.get("assets_in_uptrend"),
                "tbill_sweep_status": tbill_sweep.get("status"),
                "flatten_all_status": flatten_all.get("status"),
                "orphan_flatten_status": orphan_flatten.get("status"),
                "risk_governor_daily_pnl": risk_governor.get("daily_pnl"),
                "risk_governor_deployed_pct": risk_governor.get("deployed_pct"),
                "risk_governor_alerts": risk_governor.get("alerts_fired"),
                "earnings_vol_harvest_status": earnings_vol_harvest.get("status"),
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
                "book_net_delta": book_greeks.get("net_delta_shares"),
                "book_delta_neutral": book_greeks.get("delta_neutral"),
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
