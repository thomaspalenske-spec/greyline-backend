#!/usr/bin/env python3
"""One-shot Tue-open verification that the 6 previously-DEADLOCKED shadows actually open now.

Context (2026-09-04, commit af83e200): extended_etf/condor/iv_skew/dispersion/vol_etp/momentum_equity
settle at LIVE quotes (gate on equity_session_open) but were deferred by _heavy_blocked across exactly
the regular session — so mark() only ran when the tradeability gate fail-closed it → 0 cohorts ever.
Fix moved them to _intraday_shadow_blocked. First session it can matter is Tue Sep 8 (Mon = Labor Day).

This runs ~20 min after that open, checks each shadow opened a cohort (or, for regime/expiry shadows,
that it's ACTING not MARKET_CLOSED), texts the operator via the existing alert channel, and removes its
own launchd job. Reuses ExternalAlertEngine — no new infra.
"""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

for _ln in (ROOT / ".env").read_text().splitlines():
    _ln = _ln.strip()
    if _ln and not _ln.startswith("#") and "=" in _ln:
        _k, _, _v = _ln.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

import sys  # noqa: E402
sys.path.insert(0, str(ROOT))

LABEL = "com.greyline.shadow-open-check"

# (name, open-state path, kind). kind: 'cohort' = JSON list of open cohorts; 'ledger' = jsonl w/ status.
SHADOWS = [
    ("extended_etf", "app/data/extended_etf_shadow/open_cohort.json", "cohort"),
    ("iv_skew",      "app/data/iv_skew_shadow/open_cohort.json",       "cohort"),
    ("dispersion",   "app/data/dispersion_shadow/open_cohort.json",    "cohort"),
    ("momentum_eq",  "app/data/momentum_reversal/shadow_open_cohorts.json", "cohort"),
    ("vol_etp",      "app/data/vol_etp_shadow/open_cohort.json",        "cohort_regime"),  # regime-gated: may stay flat in contango
    ("condor",       "app/data/condor_shadow/shadow_ledger.jsonl",      "ledger"),
]
HB = "app/data/shadow_marks/heartbeats.json"
HB_KEY = {"extended_etf": "extended_etf", "iv_skew": "iv_skew", "dispersion": "dispersion",
          "momentum_eq": "momentum_equity", "vol_etp": "vol_etp", "condor": "condor"}


def _open_count(path, kind):
    p = ROOT / path
    if not p.exists():
        return 0
    try:
        if kind == "ledger":
            return sum(1 for l in p.read_text().splitlines()
                       if l.strip() and str(json.loads(l).get("status", "")).upper() == "OPEN")
        d = json.loads(p.read_text() or "[]")
        d = d if isinstance(d, list) else [d]
        return len([c for c in d if c])
    except Exception:
        return -1


def _self_remove():
    try:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, timeout=15)
    except Exception:
        pass
    try:
        (Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist").unlink(missing_ok=True)
    except Exception:
        pass


def main():
    try:
        hb = json.loads((ROOT / HB).read_text())
    except Exception:
        hb = {}
    now = time.time()

    lines, opened_core, core_total = [], 0, 0
    for name, path, kind in SHADOWS:
        n = _open_count(path, kind)
        st = (hb.get(HB_KEY[name]) or {})
        status = str(st.get("last_status", "?"))
        ran_ago = int(now - st.get("last_ran", 0)) if st.get("last_ran") else None
        acting = "MARKET_CLOSED" not in status and "DEFERRED" not in status
        # core = the always-on live-quote cohort shadows that MUST open in-session
        if kind == "cohort":
            core_total += 1
            if n >= 1:
                opened_core += 1
            flag = "opened" if n >= 1 else ("NOT opened" if acting else "market closed?")
        elif kind == "cohort_regime":
            flag = "opened" if n >= 1 else "flat (regime: contango — expected)"
        else:  # condor ledger
            flag = f"{n} open (acting)" if acting else f"{n} open (still gated?)"
        lines.append(f"{name}: {flag} [{status}"
                     + (f", {ran_ago}s ago]" if ran_ago is not None else "]"))

    all_core_open = (opened_core == core_total and core_total > 0)
    if all_core_open:
        title = "GreyLine: shadows UNFROZEN ✅"
        head = f"✅ Deadlock fix confirmed — {opened_core}/{core_total} live-quote shadows opened cohorts at the Tue open."
    else:
        title = "GreyLine: shadows — partial open ⚠️"
        head = (f"⚠️ Only {opened_core}/{core_total} live-quote shadows opened cohorts. "
                "If any read 'market closed?' the session gate may not have flipped — check.")
    msg = head + "\n\n" + "\n".join(lines)

    try:
        from app.services.external_alert_engine import ExternalAlertEngine
        ExternalAlertEngine().dispatch(title, msg, severity="INFO",
                                       fingerprint="shadow_open_check_2026_09_08", force=True)
    except Exception as e:
        print("alert dispatch failed:", str(e)[:120])
    print(title, "\n", msg)

    # one-shot: always self-remove (Tue open is a definitive read; whatever it found, it reported)
    _self_remove()


if __name__ == "__main__":
    main()
