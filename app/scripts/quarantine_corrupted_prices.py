"""Quarantine price points that cannot belong to the symbol they were filed under.

opportunity_scoring_engine passed a STALE loop variable as the price when co-recording
price points, so one instrument's quote was written under every other candidate's ticker
for weeks (fixed in 88c60cf). The damage is in app/data/price_history: every series carries
a cluster of foreign points, visible as a floor in the 92-98 band whatever the symbol
actually trades at — SPY 92.26-759.57, QQQ 92.14-746.16, META 92.32-790.00.

Until those points are removed, every fixed-horizon grade, flow-to-price join and outcome
return in the system is computed against other symbols' prices.

Truth source is app/data/historical/<SYM>_daily.csv — real daily bars for the same symbol.
A genuine intraday print sits within a tolerance band of that day's close; a foreign price
does not. Points on days with no bar (weekends, or symbols outside the daily universe) are
judged against the nearest available close instead, and kept when no reference exists at
all — absence of evidence is not evidence of corruption.

MOVES, never deletes: quarantined rows go to app/data/price_history_quarantine/ so the
call can be audited and reversed.

Usage:  PYTHONPATH=. python app/scripts/quarantine_corrupted_prices.py [--apply]
        (default is a dry run that reports and changes nothing)
"""

import csv
import json
import shutil
import sys
from bisect import bisect_left
from datetime import datetime
from pathlib import Path

PRICE_DIR = Path("app/data/price_history")
BARS_DIR = Path("app/data/historical")
QUARANTINE_DIR = Path("app/data/price_history_quarantine")

# A real intraday print can stray from the daily close, but not by half. 35% is wide enough
# to survive a gap or a volatile session and far tighter than the 8x errors being removed.
TOLERANCE = 0.35


def daily_closes(symbol):
    path = BARS_DIR / f"{symbol}_daily.csv"
    if not path.exists():
        return {}, []
    closes = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                closes[row["date"][:10]] = float(row["close"])
            except (KeyError, ValueError, TypeError):
                continue
    return closes, sorted(closes)


def reference_price(day, closes, days):
    """That day's close, or the nearest available one."""
    if day in closes:
        return closes[day]
    if not days:
        return None
    i = bisect_left(days, day)
    candidates = [d for d in (days[max(0, i - 1)], days[min(len(days) - 1, i)]) if d]
    return closes[min(candidates, key=lambda d: abs(
        (datetime.fromisoformat(d) - datetime.fromisoformat(day)).days))]


def main():
    apply = "--apply" in sys.argv
    if apply:
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    total_kept = total_bad = 0
    no_reference = []
    print(f"{'symbol':8} {'points':>7} {'quarantined':>12} {'pct':>7}   worst example")
    print("-" * 78)

    for path in sorted(PRICE_DIR.glob("*.jsonl")):
        symbol = path.stem
        closes, days = daily_closes(symbol)
        rows = []
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if not rows:
            continue
        if not closes:
            no_reference.append(symbol)
            total_kept += len(rows)
            continue

        good, bad, worst = [], [], None
        for r in rows:
            price = r.get("price")
            day = str(r.get("ts") or "")[:10]
            ref = reference_price(day, closes, days) if day else None
            if not isinstance(price, (int, float)) or price <= 0 or ref is None:
                good.append(r)
                continue
            drift = abs(price - ref) / ref
            if drift > TOLERANCE:
                bad.append(r)
                if worst is None or drift > worst[0]:
                    worst = (drift, price, ref, day)
            else:
                good.append(r)

        total_kept += len(good)
        total_bad += len(bad)
        if bad:
            pct = 100 * len(bad) / len(rows)
            ex = f"{worst[3]} price {worst[1]:.2f} vs close {worst[2]:.2f}" if worst else ""
            print(f"{symbol:8} {len(rows):>7} {len(bad):>12} {pct:>6.1f}%   {ex}")
            if apply:
                with (QUARANTINE_DIR / f"{symbol}.jsonl").open("a") as f:
                    for r in bad:
                        f.write(json.dumps(r) + "\n")
                path.write_text("".join(json.dumps(r) + "\n" for r in good))

    print("-" * 78)
    print(f"kept {total_kept} | quarantined {total_bad} "
          f"({100 * total_bad / max(1, total_kept + total_bad):.1f}% of all points)")
    if no_reference:
        print(f"\nNO DAILY BARS, left untouched (cannot judge): {', '.join(no_reference)}")
    if not apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply to move these.")


if __name__ == "__main__":
    main()
