"""Fill the tail gap in app/data/historical/*.csv from TradeStation.

The daily bars are downloaded from Yahoo, which in this environment stops ~3 weeks short
of the present (last bar 2026-06-29 while TradeStation is current to 2026-07-17). Every
backtest reads these CSVs, so the research stack has been measuring a window that ends
weeks before today while being described as current. The live trading path is unaffected —
it uses TRADESTATION_LIVE — but the seeded PriceHistoryStore inherited the same gap, which
is part of why so many flow rows grade `no_forward_price_yet`.

TradeStation has the missing bars. This appends only dates NOT already present, so it is
idempotent and cannot alter existing history.

SAFETY: these files ARE the live tradable universe (MomentumReversalStrategyEngine._symbols
globs this directory), so this script only ever APPENDS rows to files that already exist.
It never creates a symbol, never deletes, and validates each file before writing:
  * new rows must be strictly newer than the existing last date
  * dates must remain unique and sorted
  * the row count must only ever grow
A file failing validation is left untouched and reported.

Usage:  PYTHONPATH=. python app/scripts/fill_daily_bar_gap_from_tradestation.py [--apply] [--limit N]
        (default is a dry run)
"""

import csv
import sys
from datetime import datetime
from os import getenv
from pathlib import Path

import requests

BARS_DIR = Path("app/data/historical")
FIELDNAMES = ["date", "open", "high", "low", "close", "volume"]
BARS_BACK = 40          # comfortably covers a few weeks of gap


def existing_rows(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r.get("date"):
                rows.append(r)
    return rows


def fetch_bars(symbol, base_url, token):
    url = base_url.rstrip("/") + f"/v3/marketdata/barcharts/{symbol}"
    resp = requests.get(
        url,
        params={"unit": "Daily", "barsback": BARS_BACK},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    out = []
    for b in (resp.json() or {}).get("Bars", []) or []:
        ts = b.get("TimeStamp") or b.get("Timestamp")
        try:
            row = {
                "date": str(ts)[:10],
                "open": round(float(b["Open"]), 6),
                "high": round(float(b["High"]), 6),
                "low": round(float(b["Low"]), 6),
                "close": round(float(b["Close"]), 6),
                "volume": int(float(b.get("TotalVolume") or 0)),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if row["date"] and row["close"] > 0:
            out.append(row)
    out.sort(key=lambda r: r["date"])
    return out


def main():
    apply = "--apply" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine

    TradeStationTokenMaintenanceEngine().evaluate()
    token = getenv("TRADESTATION_ACCESS_TOKEN", "")
    base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
    if not token:
        raise SystemExit("no TradeStation access token")

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    paths = sorted(BARS_DIR.glob("*_daily.csv"))[:limit]
    filled = skipped = failed = 0
    added_total = 0
    rejected = []

    for path in paths:
        symbol = path.stem.replace("_daily", "")
        rows = existing_rows(path)
        if not rows:
            skipped += 1
            continue
        last_date = max(r["date"] for r in rows)
        try:
            bars = fetch_bars(symbol, base_url, token)
        except Exception:
            failed += 1
            continue

        # EXCLUDE the current session. TradeStation returns a bar for today while the
        # market is still open — a partial bar (AAPL: 15.4M volume against ~60M on a full
        # day) whose "close" is just the last print. Writing that into daily history makes
        # every backtest's final period a fraction of a session, and it would be silently
        # wrong rather than obviously wrong.
        new = [b for b in bars if last_date < b["date"] < today_iso]
        if not new:
            skipped += 1
            continue

        # Validation: strictly newer, unique, sorted, count only grows.
        dates = [b["date"] for b in new]
        if len(set(dates)) != len(dates) or dates != sorted(dates) or min(dates) <= last_date:
            rejected.append(symbol)
            continue

        added_total += len(new)
        filled += 1
        if apply:
            with open(path, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writerows(new)
            # Re-read and confirm the file only grew and stayed ordered.
            after = existing_rows(path)
            after_dates = [r["date"] for r in after]
            if len(after) != len(rows) + len(new) or after_dates != sorted(after_dates):
                rejected.append(f"{symbol} (POST-WRITE)")

    print(f"symbols scanned      : {len(paths)}")
    print(f"gap filled           : {filled}  (+{added_total} bars)")
    print(f"already current      : {skipped}")
    print(f"fetch failed         : {failed}")
    if rejected:
        print(f"REJECTED (untouched) : {len(rejected)} -> {', '.join(rejected[:10])}")
    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
