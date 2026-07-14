#!/usr/bin/env python3
"""
Backfill PriceHistoryStore for symbols that have institutional-flow snapshots but a
missing / too-sparse price series, so already-accumulated snapshots become gradable by
the fixed-horizon validators (/flow-skill-validation, /shadow-comparison).

Why this exists
---------------
The live flow↔price co-record only accumulates prices going forward. A symbol that got
flow snapshots while its price co-record was failing (or that stopped being scanned) has
snapshots that can NEVER join a price by waiting — its forward prices simply were never
recorded. This script recovers them by pulling historical bars from the TradeStation
MarketData BarCharts API and writing each bar into PriceHistoryStore at the bar timestamp.

Read-only market data only. No orders, no account mutation. Reuses the exact auth path as
the live quote engine (token maintenance + TRADESTATION_ACCESS_TOKEN + TRADESTATION_SANDBOX_URL).

Run from the repo root, on a machine with a valid TradeStation token + network:

    python backfill_price_history.py                 # all snapshot symbols, over their window
    python backfill_price_history.py --dry-run       # report gaps + planned fetches; write nothing
    python backfill_price_history.py --symbols NVDA XLU
    python backfill_price_history.py --unit Daily    # daily bars instead of 60-min intraday

Idempotent: skips bars already present within --dedup-minutes of an existing point.
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from os import getenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.tradestation_token_maintenance_engine import (
    TradeStationTokenMaintenanceEngine,
)

MEMORY_DIR = Path("app/data/institutional_memory")


# --------------------------------------------------------------------------- #
# Snapshot window discovery
# --------------------------------------------------------------------------- #
def snapshot_windows(symbols_filter=None):
    """
    Map each snapshot symbol -> (earliest_ts, latest_ts) from institutional_memory/*.jsonl.
    Returns {SYM: (first_dt, last_dt)}.
    """
    windows = {}
    if not MEMORY_DIR.exists():
        return windows
    for path in sorted(MEMORY_DIR.glob("*.jsonl")):
        sym = path.stem.upper()
        if symbols_filter and sym not in symbols_filter:
            continue
        first = last = None
        for row in read_jsonl(path):
            snap = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
            sym_row = (snap.get("symbol") or row.get("symbol") or sym).upper()
            if sym_row != sym:
                continue
            dt = _parse(row.get("timestamp"))
            if dt is None:
                continue
            first = dt if first is None or dt < first else first
            last = dt if last is None or dt > last else last
        if first is not None:
            windows[sym] = (first, last)
    return windows


# --------------------------------------------------------------------------- #
# TradeStation BarCharts fetch (read-only)
# --------------------------------------------------------------------------- #
def fetch_bars(symbol, base_url, access_token, unit, interval, barsback, timeout=30):
    """
    GET /v3/marketdata/barcharts/{symbol}. Returns list of (datetime, close) or raises.
    """
    url = base_url.rstrip("/") + f"/v3/marketdata/barcharts/{symbol}"
    params = {"unit": unit, "barsback": int(barsback)}
    if unit == "Minute":
        params["interval"] = int(interval)
    resp = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    out = []
    for bar in payload.get("Bars", []) or []:
        ts = _parse(bar.get("TimeStamp") or bar.get("Timestamp"))
        close = bar.get("Close")
        if ts is None or close in (None, "", 0, "0"):
            continue
        try:
            close = float(close)
        except (TypeError, ValueError):
            continue
        if close > 0:
            out.append((ts, close))
    out.sort(key=lambda x: x[0])
    return out


# --------------------------------------------------------------------------- #
# Coverage + gap helpers
# --------------------------------------------------------------------------- #
def existing_points(store, symbol):
    try:
        return store._load(symbol)
    except Exception:
        return []


def bars_back_needed(first_dt, unit, interval, horizon_hours, pad_days=2):
    """How many bars to request to cover [first_dt .. now + horizon] plus padding."""
    span_end = datetime.now(timezone.utc) + timedelta(hours=horizon_hours)
    first = first_dt if first_dt.tzinfo else first_dt.replace(tzinfo=timezone.utc)
    span = span_end - first + timedelta(days=pad_days)
    days = max(0, span.days)  # guard against clock skew / negative spans
    if unit == "Daily":
        return max(10, days + pad_days)
    # intraday minute bars: ~6.5 trading hours/day; be generous, cap to a sane max.
    # Floor at 120 (~18 trading days of 60-min bars) so the forward (T+horizon) side is
    # always covered even for short windows.
    per_day = max(1, int(6.5 * 60 / max(1, interval)))
    return min(57600, max(120, (days + pad_days) * per_day))


def is_new_point(new_dt, existing, dedup_minutes):
    tol = dedup_minutes * 60
    for dt, _ in existing:
        if abs((dt - new_dt).total_seconds()) <= tol:
            return False
    return True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="*", help="Limit to these symbols (default: all snapshot symbols)")
    ap.add_argument("--unit", default="Minute", choices=["Minute", "Daily"], help="Bar unit (default: Minute)")
    ap.add_argument("--interval", type=int, default=60, help="Minute interval when --unit Minute (default: 60)")
    ap.add_argument("--horizon-hours", type=float, default=24.0, help="Validation horizon to cover forward (default: 24)")
    ap.add_argument("--dedup-minutes", type=float, default=20.0, help="Skip bars within N min of an existing point (default: 20)")
    ap.add_argument("--dry-run", action="store_true", help="Report gaps + planned fetches; write nothing")
    args = ap.parse_args()

    load_dotenv(dotenv_path=Path(".env"), override=True)
    load_dotenv(dotenv_path=Path(".env.local"), override=True)

    symbols_filter = {s.upper() for s in args.symbols} if args.symbols else None
    windows = snapshot_windows(symbols_filter)
    if not windows:
        print("No snapshot symbols found (app/data/institutional_memory is empty or filtered to nothing).")
        return 0

    store = PriceHistoryStore()

    # Report current coverage vs snapshot window.
    print(f"{'SYMBOL':7} {'snapshots span':25} {'price pts':>9}  {'price span':25} status")
    plan = []
    for sym in sorted(windows):
        first, last = windows[sym]
        pts = existing_points(store, sym)
        pspan = f"{pts[0][0].date()}..{pts[-1][0].date()}" if pts else "-"
        # A symbol needs backfill if it has no points, or points don't reach snapshot_first..last+horizon.
        need = True
        if pts:
            covers_start = pts[0][0] <= first + timedelta(hours=args.horizon_hours)
            covers_fwd = pts[-1][0] >= last  # forward side often the gap
            need = not (covers_start and covers_fwd and len(pts) >= 3)
        status = "BACKFILL" if need else "ok"
        print(f"{sym:7} {str(first.date())+'..'+str(last.date()):25} {len(pts):>9}  {pspan:25} {status}")
        if need:
            plan.append((sym, first, last))

    if not plan:
        print("\nAll snapshot symbols already have adequate price coverage. Nothing to backfill.")
        return 0

    print(f"\n{len(plan)} symbol(s) to backfill: {', '.join(s for s, _, _ in plan)}")
    if args.dry_run:
        for sym, first, _ in plan:
            bb = bars_back_needed(first, args.unit, args.interval, args.horizon_hours)
            print(f"  [dry-run] {sym}: would fetch {bb} {args.unit}"
                  f"{('/'+str(args.interval)+'m') if args.unit=='Minute' else ''} bars")
        print("\nDry run — no writes performed.")
        return 0

    # Live path: ensure a fresh token, then fetch + record.
    try:
        TradeStationTokenMaintenanceEngine().evaluate()
    except Exception as e:
        print(f"WARNING: token maintenance failed ({e}); proceeding with existing token if present.")
    access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
    base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
    if not access_token:
        print("ERROR: TRADESTATION_ACCESS_TOKEN is not set. Authenticate first (see RUNBOOK), then re-run.")
        return 1

    total_written = 0
    for sym, first, last in plan:
        bb = bars_back_needed(first, args.unit, args.interval, args.horizon_hours)
        try:
            bars = fetch_bars(sym, base_url, access_token, args.unit, args.interval, bb)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"  {sym}: HTTP {code} fetching bars — skipped ({e})")
            continue
        except Exception as e:
            print(f"  {sym}: fetch failed — skipped ({e})")
            continue

        existing = existing_points(store, sym)
        written = 0
        for dt, close in bars:
            if is_new_point(dt, existing, args.dedup_minutes):
                if store.record(sym, close, dt.isoformat()):
                    existing.append((dt, close))
                    written += 1
        total_written += written
        cov = store.coverage(sym)
        print(f"  {sym}: fetched {len(bars)} bars, wrote {written} new "
              f"→ coverage now {cov['points']} pts ({cov['first']} .. {cov['last']})")

    print(f"\nDone. Wrote {total_written} new price points across {len(plan)} symbol(s).")
    print("Re-run /flow-skill-validation and /shadow-comparison to see newly-gradable outcomes "
          "(no server restart needed — validators read PriceHistoryStore live).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
