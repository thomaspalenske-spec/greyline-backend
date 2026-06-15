import json
import threading
import time
from datetime import datetime
from pathlib import Path

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.decision_scheduler_engine import DecisionSchedulerEngine
from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine
from app.services.decision_learning_memory_engine import DecisionLearningMemoryEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class BackgroundSchedulerService:
    _state_file = Path("app/data/runtime/background_scheduler_state.json")
    _thread = None
    _stop_event = threading.Event()
    _enabled = False
    _last_run = None
    _last_status = None
    _cycle_count = 0

    @classmethod
    def _load_state(cls):
        try:
            if cls._state_file.exists():
                data = json.loads(cls._state_file.read_text())
                cls._last_run = data.get("last_run")
                cls._last_status = data.get("last_status")
                cls._cycle_count = int(data.get("cycle_count", 0))
        except Exception:
            pass

    @classmethod
    def _save_state(cls):
        cls._state_file.parent.mkdir(parents=True, exist_ok=True)
        cls._state_file.write_text(json.dumps({
            "last_run": cls._last_run,
            "last_status": cls._last_status,
            "cycle_count": cls._cycle_count,
        }, indent=2))

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
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "BACKGROUND_SCHEDULER_STARTED",
        }

    @classmethod
    def stop(cls):
        cls._enabled = False
        cls._stop_event.set()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "scheduler_enabled": False,
            "execution_enabled": False,
            "order_placement_allowed": False,
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
            "execution_enabled": False,
            "order_placement_allowed": False,
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
                cls._save_state()
                ImmutableAuditLedgerEngine().record(
                    "BACKGROUND_SCHEDULER_CYCLE_FAILED",
                    {
                        "error": str(exc),
                        "execution_enabled": False,
                        "order_placement_allowed": False,
                    },
                )
            cls._stop_event.wait(interval_seconds)

    @classmethod
    def _run_cycle(cls):
        started = datetime.utcnow().isoformat()

        token = TradeStationTokenMaintenanceEngine().evaluate()
        decision = DecisionSchedulerEngine().run_manual_cycle()
        forward = ForwardOutcomeCaptureEngine().capture(limit=1)
        learning = DecisionLearningMemoryEngine().record_current_learning()
        from app.services.system_health_dashboard_engine import SystemHealthDashboardEngine
        health = SystemHealthDashboardEngine().status()

        cls._cycle_count += 1
        cls._last_run = started
        cls._last_status = "BACKGROUND_SCHEDULER_CYCLE_COMPLETE"
        cls._save_state()

        ImmutableAuditLedgerEngine().record(
            "BACKGROUND_SCHEDULER_CYCLE",
            {
                "cycle_count": cls._cycle_count,
                "token_maintenance_status": token.get("status"),
                "decision_status": decision.get("status"),
                "forward_outcome_status": forward.get("status"),
                "learning_memory_status": learning.get("status"),
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
            "token_maintenance_status": token.get("status"),
            "decision_status": decision.get("status"),
            "forward_outcome_status": forward.get("status"),
            "learning_memory_status": learning.get("status"),
            "system_health_status": health.get("status"),
            "overall_health": health.get("overall_health"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "BACKGROUND_SCHEDULER_CYCLE_COMPLETE",
        }
