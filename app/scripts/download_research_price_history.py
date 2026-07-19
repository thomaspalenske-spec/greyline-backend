"""Download daily bars for the survivorship-free research universe (2013+).

Writes to app/data/research/prices/ — NEVER app/data/historical/, which IS the live
tradable universe (MomentumReversalStrategyEngine._symbols globs it). A research download
landing there would put thousands of untested names into the next live rebalance.

Yahoo, not TradeStation, on purpose: TradeStation is ~3x faster but it is the same API the
live rebalance calls at the open, and saturating it for hours to serve a research pull is a
bad trade against a system that is booking real SIM orders tomorrow.

Resumable: an existing non-empty CSV is skipped, so this can be interrupted and restarted.
Failures are recorded rather than retried forever — delisted tickers legitimately 404.

Usage:  PYTHONPATH=. python app/scripts/download_research_price_history.py [--limit N]
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path("app/data/research/prices")
STATE = Path("app/data/research/download_state.json")
START = "2012-01-01"          # a year before 2013 so the 12-1 momentum signal has history
THROTTLE_SECONDS = 0.4
UA = "Mozilla/5.0 GreyLineResearchDownloader/1.0"


def _unix(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def fetch(symbol):
    """Daily bars for `symbol`, or None if Yahoo has nothing (delisted names often 404)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?" + \
        urllib.parse.urlencode({
            "period1": _unix(START),
            "period2": int(datetime.now(timezone.utc).timestamp()),
            "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    stamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    adj = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    rows = []
    for i, ts in enumerate(stamps):
        try:
            o, h, l = quote["open"][i], quote["high"][i], quote["low"][i]
            c, v = quote["close"][i], quote["volume"][i]
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c, v):
            continue
        rows.append({
            "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
            # Splits/dividends make raw closes lie about returns; the momentum signal needs
            # the adjusted series. Kept alongside so cost models can use the traded price.
            "adj_close": (adj[i] if i < len(adj) and adj[i] is not None else c),
        })
    return rows or None


def write_csv(symbol, rows):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # ':' and '/' in tickers would break paths; UW uses '-' but be defensive.
    safe = symbol.replace("/", "_").replace(":", "_")
    path = OUT_DIR / f"{safe}_daily.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume", "adj_close"])
        w.writeheader()
        w.writerows(rows)
    return path


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.research.point_in_time_universe_engine import PointInTimeUniverseEngine

    engine = PointInTimeUniverseEngine()
    union = set()
    for year in range(2013, 2027):
        for month in (1, 7):
            as_of = f"{year}-{month:02d}-01"
            if as_of <= datetime.utcnow().strftime("%Y-%m-%d"):
                union |= set(engine.resolve(as_of))
    symbols = sorted(union)[:limit] if limit else sorted(union)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = {p.name.replace("_daily.csv", "") for p in OUT_DIR.glob("*_daily.csv") if p.stat().st_size > 0}
    todo = [s for s in symbols if s.replace("/", "_").replace(":", "_") not in done]

    print(f"universe {len(symbols)} | already have {len(done)} | fetching {len(todo)}", flush=True)
    ok = empty = failed = 0
    t0 = time.time()
    for i, sym in enumerate(todo, 1):
        try:
            rows = fetch(sym)
            if rows:
                write_csv(sym, rows); ok += 1
            else:
                empty += 1
        except urllib.error.HTTPError as e:
            failed += 1
            if e.code == 429:      # rate limited — back off hard rather than burn the run
                print(f"  429 at {sym}; sleeping 60s", flush=True)
                time.sleep(60)
        except Exception:
            failed += 1
        if i % 250 == 0:
            rate = i / max(1e-9, time.time() - t0)
            print(f"  {i}/{len(todo)} ok={ok} empty={empty} failed={failed} "
                  f"| {rate:.1f}/s | eta {(len(todo)-i)/max(rate,1e-9)/60:.0f} min", flush=True)
            STATE.write_text(json.dumps({"at": datetime.utcnow().isoformat(), "done": i,
                                         "total": len(todo), "ok": ok, "empty": empty,
                                         "failed": failed}))
        time.sleep(THROTTLE_SECONDS)

    summary = {"finished_at": datetime.utcnow().isoformat(), "universe": len(symbols),
               "fetched": ok, "no_data": empty, "failed": failed,
               "minutes": round((time.time() - t0) / 60, 1)}
    STATE.write_text(json.dumps(summary))
    print("DONE", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
