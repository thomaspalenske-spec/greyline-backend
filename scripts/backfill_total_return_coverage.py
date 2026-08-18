"""One-time backfill: build the dividend-adjusted total-return series for every MIN_BARS-eligible name in
the momentum universe that lacks one — so the just-armed GREYLINE_MOMENTUM_TOTAL_RETURN wiring covers the
whole tradeable universe (was ~44%), not a stale subset. Junk (warrants/units/micro-caps < MIN_BARS) is
excluded upstream by the eligibility gate. Idempotent: skips names already built. Rate-limited by the UW
provider. Run in the background; progress prints every 25 names."""

import glob
import os
import sys

sys.path.insert(0, os.getcwd())

from app.services.env_reload import reload_env
reload_env()

from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.total_return_series_engine import TotalReturnSeriesEngine

MIN_BARS = DirectionalSignalEngine.MIN_BARS


def _bars(path):
    try:
        with open(path) as f:
            return sum(1 for _ in f) - 1
    except Exception:
        return 0


def main():
    have = {os.path.basename(p).replace("_total_return.csv", "").upper()
            for p in glob.glob("app/data/historical_total_return/*_total_return.csv")}
    eligible = []
    for p in glob.glob("app/data/historical/*_daily.csv"):
        sym = os.path.basename(p).replace("_daily.csv", "").upper()
        if sym not in have and _bars(p) >= MIN_BARS:
            eligible.append(sym)
    eligible.sort()
    print(f"[backfill] {len(eligible)} eligible uncovered names to build (MIN_BARS={MIN_BARS})", flush=True)

    eng = TotalReturnSeriesEngine()
    built = failed = divs = 0
    for i, sym in enumerate(eligible, 1):
        try:
            r = eng.build_symbol(sym, save=True)
            if r.get("status") == "TOTAL_RETURN_BUILT":
                built += 1
                divs += r.get("dividends_applied", 0) or 0
            else:
                failed += 1
        except Exception as e:
            failed += 1
            if failed <= 10:
                print(f"[backfill] FAIL {sym}: {str(e)[:80]}", flush=True)
        if i % 25 == 0:
            print(f"[backfill] {i}/{len(eligible)}  built={built} failed={failed} divs_applied={divs}", flush=True)
    print(f"[backfill] DONE built={built} failed={failed} total_dividends_applied={divs}", flush=True)


if __name__ == "__main__":
    main()
