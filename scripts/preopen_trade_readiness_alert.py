#!/usr/bin/env python3
"""Pre-open trade-readiness alert — the launchd runner.

Runs GreyLine's end-to-end "can it trade when the market opens?" audit and texts the operator a concise
GO/NO-GO via the existing iMessage alert path (ExternalAlertEngine). Read-only: it never places an
order, arms/disarms anything, or writes state beyond the alert dedup ledger.

launchd fires this Mon-Fri at 08:02 local (see com.greyline.preopen-readiness.plist); this script skips
market HOLIDAYS itself (cron/launchd can't express them). Run with --dry-run to print the message and
what WOULD be sent, without texting.

    .venv/bin/python3 scripts/preopen_trade_readiness_alert.py [--dry-run]
"""

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

# Engines resolve app/data/... relative to CWD — pin it to the repo root so launchd's CWD can't matter.
REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
sys.path.insert(0, str(REPO))

DRY = "--dry-run" in sys.argv[1:]

# The links that MUST be healthy for a decided order to actually book (mirrors the e2e test).
SPINE_CRITICAL = ("execution_authority", "broker_connectivity", "sim_booking_target_safe",
                  "order_path_integrity", "reality_guard")
SLEEVE_FLAGS = [("momentum", "GREYLINE_MOMENTUM_ENABLED"), ("vrp", "GREYLINE_VRP_SHORT_PREMIUM_ENABLED"),
                ("earnings", "GREYLINE_EARNINGS_VOL_ENABLED"), ("vol_carry", "GREYLINE_VOL_CARRY_ENABLED"),
                ("trend", "GREYLINE_TREND_ENABLED"), ("tbill", "GREYLINE_TBILL_SWEEP_ENABLED")]


def _live_scheduler():
    """Real scheduler-thread state from the running service (thread_alive is process-local)."""
    try:
        pw = os.getenv("GREYLINE_DASHBOARD_PASSWORD", "")
        req = urllib.request.Request("http://127.0.0.1:8000/background-scheduler/status")
        if pw:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"audit:{pw}".encode()).decode())
        with urllib.request.urlopen(req, timeout=6) as r:   # noqa: S310 (localhost only)
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_unreachable": repr(e)[:80]}


def _flag(name):
    return (os.getenv(name, "") or "").strip().lower() == "true"


def main():
    from app.services.env_reload import reload_env
    reload_env()

    # 1. skip market holidays (launchd already restricts to Mon-Fri)
    try:
        from app.services.market_hours_engine import MarketHoursEngine
        mh = MarketHoursEngine().status()
        if str(mh.get("is_holiday")) == "True":
            print("HOLIDAY — market closed today; audit skipped, no alert sent.")
            return 0
    except Exception as e:
        print(f"market-hours check failed ({e!r}); continuing with the audit anyway.")

    # 2. run the audit (may hit the live broker — allow time)
    try:
        from app.services.pre_open_readiness_engine import PreOpenReadinessEngine
        report = PreOpenReadinessEngine().audit()
    except Exception as e:
        title = "GreyLine pre-open audit FAILED to run"
        msg = f"🔴 The trade-readiness audit could not run before the open: {e!r}. Check the service NOW."
        return _emit(title, msg, "CRITICAL")

    checks = {c["check"]: c for c in report["checks"]}
    spine_fail = [n for n in SPINE_CRITICAL if checks.get(n, {}).get("status") == "FAIL"]
    # scheduler_liveness WARN is a process-local artifact (this runner has no trading thread) — the real
    # thread state comes from the live-service HTTP check below, so don't surface it as a warning.
    warns = [c["check"] for c in report["checks"]
             if c["status"] == "WARN" and c["check"] != "scheduler_liveness"]
    armed = [name for name, flag in SLEEVE_FLAGS if _flag(flag)]
    off = [name for name, flag in SLEEVE_FLAGS if not _flag(flag)]
    mom = checks.get("momentum_path", {}).get("detail", "")
    mom_due = mom.split("next due", 1)[1].strip() if "next due" in mom else "n/a"
    sched = _live_scheduler()
    sched_line = ("service unreachable" if "_unreachable" in sched
                  else f"thread_alive={sched.get('thread_alive')}, last={sched.get('last_status')}")

    if spine_fail:
        title = "GreyLine NOT ready to trade at open"
        broken = "\n".join(f"- {n}: {checks[n]['detail']}" for n in spine_fail)
        msg = (f"🔴 SPINE NO-GO (route overall {report['overall']}). Broken link(s):\n{broken}\n"
               f"Scheduler: {sched_line}. Fix before the open.")
        return _emit(title, msg, "CRITICAL")

    title = "GreyLine READY to trade at open"
    msg = (f"🟢 SPINE GO (route overall {report['overall']}, {report['fail_count']} fail / "
           f"{report['warn_count']} warn).\n"
           f"Armed: {', '.join(armed) or 'NONE'}" + (f" | off: {', '.join(off)}" if off else "") + ".\n"
           f"Momentum next due {mom_due}. Scheduler: {sched_line}."
           + (f"\nWarns: {', '.join(warns)}." if warns else ""))
    return _emit(title, msg, "INFO")


def _emit(title, message, severity):
    from datetime import datetime
    from app.services.external_alert_engine import ExternalAlertEngine
    eng = ExternalAlertEngine()
    day = datetime.utcnow().date().isoformat()
    fp = f"PREOPEN_READINESS:{day}"
    print(f"[{severity}] {title}\n{message}\n")
    if DRY:
        print("DRY-RUN — not sent. dispatch preview:",
              json.dumps(eng.dispatch(title, message, severity, fingerprint=fp, dry_run=True)))
        return 0
    if not eng.has_external_channel():
        print("WARNING: no external alert channel configured — alert stays on this machine.")
    res = eng.dispatch(title, message, severity, fingerprint=fp, force=True)
    print("dispatch result:", json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
