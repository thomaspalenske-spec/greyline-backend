"""Cycle-failure forensics — turn the scheduler's black-box failure COUNT into a diagnosable record.

WHY: BackgroundSchedulerService keeps only `_last_error` (cleared on the next success) and a rolling
in-memory `recent_cycles` (capped at 20). So a lifetime failure_count of 300+ carries ZERO detail — you
can't tell what failed, in which phase, or whether any failure landed on the 09:30 open where the armed
VRP/momentum entries fire. A failed cycle at the open = a missed entry = a lost court-day, invisibly. The
confirmed-edge VRP sleeve needs ~20 CLEAN independent trading days to prove out, so an uncharacterized ~8%
cycle-failure rate is the single biggest uncontrolled threat to that proof.

WHAT: on each FAILED cycle, append one classified record to an append-only JSONL — timestamp, error class
(TradeStation / Unusual Whales / broker-read / timeout / network / code-bug / …), the last completed phase
(the failure locus), the market session, and the SIGNED minutes to the 09:30 ET open (so 'near the open'
failures are countable). `summary()` aggregates it for the route + dashboard. Pure record/aggregate — it
never raises into the cycle (best-effort, like the continuity heartbeat)."""

import re
from datetime import datetime, time
from pathlib import Path

from app.services.persistence.json_store import append_jsonl, read_jsonl


class CycleFailureForensicsEngine:

    LOG = Path("app/data/continuity/cycle_failures.jsonl")
    _READ_CAP = 2000                 # tail-cap reads so the file can grow append-only without unbounded parse
    NEAR_OPEN_MIN = 20               # |minutes to 09:30 ET| <= this == an open-critical failure (entry at risk)

    # error string (lower-cased) -> class. First match wins, so order most-specific first. The point is a
    # SMALL stable set of actionable buckets, not a taxonomy: "is it the broker, the data vendor, the
    # network, our code, or the clock?" — each implies a different fix.
    _RULES = [
        ("UW_RATE_LIMIT",      ("unusual", "429", "rate limit", "too many requests")),
        ("UW_DATA",            ("unusualwhales", "uw ", "/api/", "whale")),
        ("TS_AUTH",            ("token", "unauthorized", "401", "invalid_grant", "refresh")),
        # BROKER_READ before TS_ORDER: a positions/balances read failure also comes from the
        # brokerage/accounts path, so the read signals ('positions'/'balances'/'degraded') must win over the
        # broad order signals — otherwise a fail-closed broker read is miscounted as an order reject.
        ("BROKER_READ",        ("positions", "balances", "degraded", "fail-closed", "fail closed")),
        ("TS_ORDER",           ("order", "buytoopen", "selltoclose", "place_order", "reject")),
        ("TS_QUOTE",           ("quote", "marketdata", "barchart", "tradestation")),
        ("TIMEOUT",            ("timeout", "timed out", "read timed", "deadline")),
        ("NETWORK",            ("connection", "connectionerror", "ssl", "econn", "dns", "getaddrinfo",
                                "max retries", "remote end closed")),
        ("MARKET_HOURS",       ("market_hours", "markethours", "is_regular_session")),
        ("CODE_BUG",           ("keyerror", "typeerror", "valueerror", "attributeerror", "indexerror",
                                "nonetype", "traceback", "unboundlocal", "zerodivision")),
        ("MEMORY",             ("memoryerror", "out of memory", "oom")),
    ]

    @classmethod
    def classify(cls, error):
        """Map a raw error string to one stable actionable bucket. Unknown -> OTHER (never raises)."""
        s = str(error or "").lower()
        if not s.strip():
            return "UNKNOWN"
        for label, needles in cls._RULES:
            if any(n in s for n in needles):
                return label
        return "OTHER"

    @staticmethod
    def _now_et():
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            st = MarketHoursEngine().status()
            return datetime.fromisoformat(st["market_time"]), st
        except Exception:
            return None, {}

    @classmethod
    def _minutes_to_open(cls, now_et, mh):
        """Signed minutes from `now_et` to TODAY's 09:30 ET open: negative before the open (premarket),
        positive after. None on a non-trading day or if the ET clock can't be resolved — those failures
        can't threaten an entry, so they're simply not 'near the open'. """
        try:
            if now_et is None or not mh.get("is_weekday") or mh.get("is_holiday"):
                return None
            open_dt = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            return round((now_et - open_dt).total_seconds() / 60.0, 1)
        except Exception:
            return None

    @classmethod
    def record(cls, error, phase_hint=None, at=None):
        """Append one classified failure record. Best-effort — swallows everything so it can never turn a
        cycle failure into a crash. `phase_hint` is the last COMPLETED phase (failure locus is just after)."""
        try:
            now_et, mh = cls._now_et()
            mins = cls._minutes_to_open(now_et, mh)
            rec = {
                "at": (at or datetime.utcnow().isoformat()),
                "error_class": cls.classify(error),
                "error": (str(error or "")[:300]),
                "phase_after": phase_hint or None,
                "session": mh.get("state"),
                "minutes_to_open": mins,
                "near_open": (mins is not None and abs(mins) <= cls.NEAR_OPEN_MIN),
            }
            append_jsonl(cls.LOG, rec)
            return rec
        except Exception:
            return None

    @staticmethod
    def _phase_hint_from_timings(timings):
        """Best-effort failure locus: the last instrumented phase that COMPLETED before the throw. The real
        failing phase is the one just after it. Ignores the synthetic _total key."""
        try:
            keys = [k for k in (timings or {}) if not str(k).startswith("_")]
            return keys[-1] if keys else None
        except Exception:
            return None

    @classmethod
    def summary(cls, limit=500):
        """Aggregate the recorded failures for the route/dashboard: totals, by-class, near-open count,
        session breakdown, and the most recent handful. Reads only the tail so it stays cheap."""
        rows = read_jsonl(cls.LOG) or []
        rows = rows[-max(1, min(int(limit or 500), cls._READ_CAP)):]
        by_class, by_session = {}, {}
        near_open = 0
        for r in rows:
            by_class[r.get("error_class", "UNKNOWN")] = by_class.get(r.get("error_class", "UNKNOWN"), 0) + 1
            sess = r.get("session") or "UNKNOWN"
            by_session[sess] = by_session.get(sess, 0) + 1
            if r.get("near_open"):
                near_open += 1
        ranked = sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
        near_rows = [r for r in rows if r.get("near_open")]
        return {
            "recorded": len(rows),
            "near_open_failures": near_open,           # the ones that could have cost a court-day
            "by_class": [{"class": k, "count": v} for k, v in ranked],
            "by_session": by_session,
            "recent": rows[-8:][::-1],                 # newest first
            "recent_near_open": near_rows[-5:][::-1],
            "note": ("Classified scheduler cycle failures. near_open = |minutes to 09:30 ET| <= %d, i.e. a "
                     "failure that could have missed an armed entry. Forward-only from first deploy; the "
                     "pre-existing lifetime failure_count predates this record." % cls.NEAR_OPEN_MIN),
            "status": "CYCLE_FAILURE_FORENSICS",
        }
