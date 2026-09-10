"""Contamination windows — periods whose trades must NOT count toward Edge Court verdicts.

A programming bug in the execution layer (e.g. the 2026-09-10 low_vol cash-clamp churn: target
collapsed to 0 on a cash dip -> sell-all -> rebuy, ~52 wash round-trips/day) fills the sleeve ledgers
with trades that are ARTIFACTS, not strategy outcomes. Counting them toward a sleeve's live edge is the
same error the court already guards against for forced/administrative flattens — so exclude them the same
way. This registry is the durable list of {sleeve, from, to, reason} periods to drop.

Two producers:
  * a one-time SEED (a known-bad forward-test, e.g. low_vol's entire pre-fix life) written by hand/ops;
  * the reality guard's live detectors (NO_SLEEVE_CHURN, FREE_CASH_NOT_NEGATIVE) calling record() when
    they fire, so a future bug the guards catch AUTOMATICALLY stops polluting the science.

Fail-safe: any read/parse error returns NO windows (never crashes or over-excludes the court). record()
MERGES an overlapping/adjacent window for the same (sleeve, reason) instead of appending, so a detector
firing every scheduler cycle extends one window rather than spamming thousands.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path


class ContaminationWindowEngine:
    FILE = Path("app/data/edge_court/contamination_windows.json")
    MERGE_GAP_HOURS = 24        # a new window within this gap of an existing same-(sleeve,reason) one extends it

    @classmethod
    def _load_raw(cls):
        try:
            d = json.loads(cls.FILE.read_text())
            w = d.get("windows") if isinstance(d, dict) else d
            return list(w) if isinstance(w, list) else []
        except Exception:
            return []

    @classmethod
    def windows(cls):
        """Sanitized list of {sleeve, from, to, reason}. Bad entries are dropped, never raised."""
        out = []
        for w in cls._load_raw():
            if not isinstance(w, dict):
                continue
            frm, to = str(w.get("from") or ""), str(w.get("to") or "")
            if not frm or not to:
                continue
            out.append({"sleeve": str(w.get("sleeve") or "*"), "from": frm, "to": to,
                        "reason": str(w.get("reason") or "")})
        return out

    @staticmethod
    def _in(ts, frm, to):
        try:
            return frm <= str(ts)[:len(frm)] and str(ts)[:len(to)] <= to
        except Exception:
            return False

    @classmethod
    def is_contaminated(cls, sleeve, closed_at, _windows=None):
        """True if a close at `closed_at` (naive-UTC ISO string) for `sleeve` falls in a window.
        A window with sleeve '*' matches every sleeve. None/blank closed_at -> NOT contaminated (we can't
        place it, so we don't over-exclude)."""
        if not closed_at:
            return False
        wins = _windows if _windows is not None else cls.windows()
        s = str(sleeve or "")
        for w in wins:
            if w["sleeve"] not in ("*", s):
                continue
            # ISO strings compare lexicographically in chronological order when same-length-prefixed
            if w["from"] <= str(closed_at) <= w["to"]:
                return True
        return False

    @classmethod
    def record(cls, sleeve, from_ts, to_ts, reason):
        """Register (or extend) a contamination window. Merges with the most recent window of the same
        (sleeve, reason) when the new one overlaps or is within MERGE_GAP_HOURS of it — so a live detector
        firing repeatedly extends ONE window. Best-effort; never raises into the caller."""
        try:
            from_ts, to_ts = str(from_ts), str(to_ts)
            if not from_ts or not to_ts or to_ts < from_ts:
                return False
            raw = cls._load_raw()
            merged = False
            for w in raw:
                if str(w.get("sleeve")) != str(sleeve) or str(w.get("reason")) != str(reason):
                    continue
                w_to = str(w.get("to") or "")
                w_from = str(w.get("from") or "")
                try:
                    gap_ok = (datetime.fromisoformat(from_ts) - datetime.fromisoformat(w_to)
                              <= timedelta(hours=cls.MERGE_GAP_HOURS))
                except Exception:
                    gap_ok = from_ts <= w_to     # fall back to overlap-only if timestamps unparseable
                if from_ts <= w_to or gap_ok:    # overlaps or adjacent -> extend
                    w["to"] = max(w_to, to_ts)
                    w["from"] = min(w_from, from_ts) if w_from else from_ts
                    merged = True
                    break
            if not merged:
                raw.append({"sleeve": str(sleeve), "from": from_ts, "to": to_ts, "reason": str(reason)})
            cls.FILE.parent.mkdir(parents=True, exist_ok=True)
            cls.FILE.write_text(json.dumps({"windows": raw}, indent=1))
            return True
        except Exception:
            return False
