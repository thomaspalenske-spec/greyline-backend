"""Seed PriceHistoryStore with historical daily closes so backfilled flow can be graded.

UWFlowGradingEngine scores flow against the NEXT day's close via _daily_close(), which
reads the forward price feed. That feed was populated only by live scheduler cycles and is
6-7 days deep, so reconstructing 60 days of institutional flow would still have produced
INSUFFICIENT: 65 days of signal with 7 days of outcomes to score it against.

The daily bars downloaded for the trading universe cover 1998-2026, so the outcomes already
exist on disk — they were just never in the store the grader reads.

Deliberately conservative about the live feed:
  * one point per trading day (the close), which is what _daily_close collapses to anyway;
  * seeded points are stamped 20:00 UTC, after the US close, so on any day that also has
    live intraday points the seeded close sorts last and wins — which is correct, it IS
    the close;
  * days already carrying a seeded close are skipped, so reruns are idempotent;
  * only symbols with flow data are touched. This is not a general price backfill.

Usage:  PYTHONPATH=. python app/scripts/seed_price_history_from_daily_bars.py [--days 400]
"""

import csv
import glob
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BARS_DIR = Path("app/data/historical")
FLOW_DIR = Path("app/data/uw_flow")
SEED_HOUR = "T20:00:00"        # after the US close; sorts after live intraday points


def flow_symbols():
    return sorted(os.path.basename(p)[:-6] for p in glob.glob(str(FLOW_DIR / "*.jsonl")))


def daily_closes(symbol, since):
    path = BARS_DIR / f"{symbol}_daily.csv"
    if not path.exists():
        return None
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                day = row["date"][:10]
                close = float(row["close"])
            except (KeyError, ValueError, TypeError):
                continue
            if day >= since and close > 0:
                out[day] = close
    return out


def fetch_closes_from_yahoo(symbol, since):
    """Daily closes for a symbol with no local bars (crypto trusts, non-index names).

    Returns adjusted closes keyed by day, or None if Yahoo has nothing. Writes nothing to
    disk itself — the caller seeds the price store only.
    """
    import json as _json
    import urllib.parse
    import urllib.request
    from datetime import timezone

    start = int(datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?" + \
        urllib.parse.urlencode({"period1": start,
                                "period2": int(datetime.now(timezone.utc).timestamp()),
                                "interval": "1d", "events": "history",
                                "includeAdjustedClose": "true"})
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 GreyLinePriceSeeder/1.0",
        "Accept": "application/json,text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    stamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out = {}
    for i, ts in enumerate(stamps):
        try:
            px = closes[i]
        except IndexError:
            continue
        if px:
            out[datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")] = float(px)
    return out or None


def existing_seeded_days(store, symbol):
    """Days that already carry a seeded close, so a rerun adds nothing."""
    seen = set()
    for dt, _ in store._load(symbol):
        if dt.strftime("%H:%M:%S") == "20:00:00":
            seen.add(dt.date().isoformat())
    return seen


def main():
    days_back = 400
    if "--days" in sys.argv:
        days_back = int(sys.argv[sys.argv.index("--days") + 1])

    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.price_history_store import PriceHistoryStore

    store = PriceHistoryStore()
    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    symbols = flow_symbols()

    fetch_missing = "--fetch-missing" in sys.argv

    seeded = skipped = 0
    no_bars = []
    for symbol in symbols:
        closes = daily_closes(symbol, since)
        if closes is None and fetch_missing:
            # Fetched straight into the price store, NOT into app/data/historical — that
            # directory is the live tradable universe, and a research need must not
            # quietly make two crypto trusts buyable by the strategy.
            closes = fetch_closes_from_yahoo(symbol, since)
        if closes is None:
            # No daily CSV: the symbol is outside the price universe (e.g. crypto trusts).
            # Reported, never silently treated as "no history".
            no_bars.append(symbol)
            continue
        already = existing_seeded_days(store, symbol)
        points = [(symbol, px, f"{day}{SEED_HOUR}")
                  for day, px in sorted(closes.items()) if day not in already]
        skipped += len(closes) - len(points)
        seeded += store.record_batch(points)

    summary = {"timestamp": datetime.utcnow().isoformat(),
               "symbols": len(symbols), "points_seeded": seeded,
               "already_present": skipped, "no_daily_bars": no_bars,
               "since": since, "status": "PRICE_HISTORY_SEEDED"}
    print(json.dumps(summary, indent=2))
    if no_bars:
        print("\nNO DAILY BARS (flow for these cannot be graded until prices exist):")
        print("  " + ", ".join(no_bars))


if __name__ == "__main__":
    main()
