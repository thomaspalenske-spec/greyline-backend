#!/usr/bin/env python3
"""One-shot post-open check of the 4 untracked-condor CLOSING orders placed 2026-09-04.

Context: 4 iron condors (IEF/IWM/RSP/TLT, Oct-16) sat in the SIM account untracked by any
GreyLine ledger. On 2026-09-04 (Fri, after close) we placed 4 atomic GTC limit closes; with
Mon Sep 7 = Labor Day, they fill at the Tue Sep 8 open. This script runs ~15 min after that
open, reports fill status to the operator's phone via the existing alert channel, and then
REMOVES ITS OWN launchd job so it never fires again (true one-shot).

Reuses: TradeStationTokenMaintenanceEngine (token), ExternalAlertEngine (iMessage). No new infra.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# load .env the same lightweight way the ad-hoc checks did
for _ln in (ROOT / ".env").read_text().splitlines():
    _ln = _ln.strip()
    if _ln and not _ln.startswith("#") and "=" in _ln:
        _k, _, _v = _ln.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

import requests  # noqa: E402

ORDERS = {"970198467": "RSP", "970198468": "IEF", "970198469": "IWM", "970198470": "TLT"}
ACCT = "SIM3288615M"
BASE = "https://sim-api.tradestation.com"
LABEL = "com.greyline.condor-fill-check"


def _self_remove():
    """Bootout this launchd job and delete its plist so it never fires again."""
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    try:
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                       capture_output=True, timeout=15)
    except Exception:
        pass
    try:
        plist.unlink(missing_ok=True)
    except Exception:
        pass


def main():
    try:
        from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
        TradeStationTokenMaintenanceEngine().evaluate()
    except Exception:
        pass
    tok = os.getenv("TRADESTATION_ACCESS_TOKEN", "")
    hdr = {"Authorization": f"Bearer {tok}"}

    # order statuses
    lines, filled = [], 0
    try:
        r = requests.get(f"{BASE}/v3/brokerage/accounts/{ACCT}/orders", headers=hdr, timeout=25)
        by_id = {o.get("OrderID"): o for o in (r.json().get("Orders", []) or [])}
    except Exception as e:
        by_id = {}
        lines.append(f"(order read failed: {str(e)[:60]})")
    for oid, name in ORDERS.items():
        o = by_id.get(oid) or {}
        stat = str(o.get("StatusDescription") or o.get("Status") or "UNKNOWN")
        if stat.upper().startswith("FIL") or o.get("Status") == "FLL":
            filled += 1
        lines.append(f"{name}: {stat}")

    # remaining untracked condor legs
    try:
        p = requests.get(f"{BASE}/v3/brokerage/accounts/{ACCT}/positions", headers=hdr, timeout=25)
        legs = [x.get("Symbol") for x in (p.json().get("Positions", []) or [])
                if "261016" in str(x.get("Symbol", ""))
                and str(x.get("Symbol", "")).split()[0] in ("IEF", "IWM", "RSP", "TLT")]
    except Exception:
        legs = None

    flat = (legs == [])
    if flat:
        title = "GreyLine: condors CLOSED"
        head = "✅ All 4 untracked condors (IEF/IWM/RSP/TLT) are flat. Reality-Guard untracked + "\
               "broker-side-protection warnings should now clear."
    elif legs is None:
        title = "GreyLine: condor check (positions unread)"
        head = "⚠️ Could not read positions. Order statuses below — verify in TradeStation."
    else:
        title = "GreyLine: condors NOT fully closed"
        head = f"⚠️ {len(legs)} of 16 condor legs still open. Orders may be unfilled — check TradeStation."

    msg = head + "\n\n" + "\n".join(lines)
    if legs:
        msg += f"\n\nOpen legs: {len(legs)}"

    try:
        from app.services.external_alert_engine import ExternalAlertEngine
        ExternalAlertEngine().dispatch(title, msg, severity="INFO",
                                       fingerprint="condor_fill_check_2026_09_08", force=True)
    except Exception as e:
        print("alert dispatch failed:", str(e)[:120])
    print(title, "\n", msg)

    # one-shot: only self-remove once we have a definitive flat result; otherwise leave the job
    # so a later manual run / reschedule can retry. (If unfilled, operator was just texted.)
    if flat:
        _self_remove()


if __name__ == "__main__":
    main()
