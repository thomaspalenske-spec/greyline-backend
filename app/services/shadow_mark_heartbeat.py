"""Uniform per-shadow mark heartbeat — the generalized 'condor resilience' surfacing fix.

WHY THIS EXISTS (2026-08-25): the zero-capital forward-test shadows (condor / gex / iv-skew / dispersion
/ ... ) each `mark()` late in the scheduler cycle. When the PROCESS stalled for days (the 2026-08-16 CPU
hot-loop peg where `kickstart -k` silently failed, compounded by the 08-24 power-loss clock chaos), the
heavy-gated shadows silently stopped accruing — condor and gex both froze at 08-17 and it was only caught
by chance when Thomas looked at the GEX card a week later. Nothing SURFACED the stall.

The scheduler's per-step try/except already stops one shadow's EXCEPTION from starving the others, and the
`_ckpt` marks prove the block was *reached*. What was missing is a persisted, cadence-INDEPENDENT signal of
when each shadow last actually RAN its mark logic (not merely was reached-then-deferred). Reading a shadow's
own state file doesn't work for the cohort shadows (iv-skew is weekly, dispersion monthly) — they legitimately
write nothing between cohorts, so state-file freshness would cry wolf. A dedicated 'last actually ran' heartbeat
is cadence-independent: every enabled shadow runs mark() ~nightly when not deferred, so a multi-day gap in
`last_ran` is an unambiguous silent stall regardless of cohort cadence.

CONTRACT: the scheduler calls `record(results)` once, right after the shadow block, passing the already-computed
per-shadow result dicts. We stamp `last_ran` only when the shadow actually executed (status carries no DEFERRED /
DISABLED marker and no hard error). GreylineRealityGuardEngine._check_shadow_freshness reads this file, and — only
when the scheduler is live and the shadow is enabled — raises a warning-severity banner line if any enabled
shadow's last real run is older than the staleness threshold.

BULLETPROOF: monitoring must NEVER be able to break the trading cycle, so every write path swallows all errors.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

HEARTBEAT_FILE = Path("app/data/shadow_marks/heartbeats.json")

# A status string carrying any of these means the shadow did NOT actually run its mark logic this cycle
# (it was gate-deferred, disabled, or errored) — so we must NOT refresh its `last_ran` timestamp, otherwise a
# shadow that is deferred every single cycle (e.g. a stuck-in-market-hours clock) would look perpetually fresh.
_DID_NOT_RUN_MARKERS = ("DEFERRED", "DISABLED", "_DEGRADED", "ERROR")


def _ran(result) -> bool:
    """True iff the shadow actually executed its mark/settle logic this cycle."""
    try:
        if not isinstance(result, dict):
            return False
        if result.get("error"):
            return False
        status = str(result.get("status") or "").upper()
        if any(m in status for m in _DID_NOT_RUN_MARKERS):
            return False
        return True
    except Exception:
        return False


def _read_raw() -> dict:
    try:
        if HEARTBEAT_FILE.exists():
            data = json.loads(HEARTBEAT_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def record(results: dict) -> None:
    """Stamp heartbeats for the shadow results computed this cycle. `results` maps shadow_id -> result dict.

    `last_ran` advances only when the shadow actually ran (see `_ran`); `last_seen` and `last_status` update
    every cycle the block reached the shadow, so a reader can tell 'block never reached it' from 'reached but
    deferred'. Bulletproof — any failure is swallowed."""
    try:
        state = _read_raw()
        now = time.time()
        for sid, result in (results or {}).items():
            row = state.get(sid) or {}
            ran = _ran(result)
            try:
                status = str(result.get("status")) if isinstance(result, dict) else str(result)
            except Exception:
                status = None
            row["last_seen"] = now
            row["last_status"] = (status or "")[:80]
            if ran:
                row["last_ran"] = now
            state[str(sid)] = row
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEARTBEAT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(HEARTBEAT_FILE)
    except Exception:
        pass


def read() -> dict:
    """Return the persisted heartbeat map (shadow_id -> {last_ran, last_seen, last_status}). Never raises."""
    return _read_raw()
