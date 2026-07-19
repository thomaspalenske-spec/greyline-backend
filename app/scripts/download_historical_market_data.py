from datetime import date, datetime, timezone
from pathlib import Path
import csv
import time
import urllib.request
import urllib.parse
import json


DATA_DIR = Path("app/data/historical")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def sp500_symbols():
    """Current S&P 500 constituents from Unusual Whales (SPY holdings).

    This replaces a hand-typed list as the definition of the tradable universe.
    MomentumReversalStrategyEngine._symbols() globs the CSVs this writes, so whatever
    lands here IS what the strategy may select — the list was the shackle, not the code.

    Returns ~504 tickers: the index holds 500 companies but several have dual share
    classes (GOOG/GOOGL, FOX/FOXA, NWS/NWSA).
    """
    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider

    resp = UnusualWhalesProvider()._get("/api/etfs/SPY/holdings", params={"limit": 600})
    rows = (resp.get("data") if isinstance(resp, dict) else resp) or []
    tickers = sorted({r.get("ticker") for r in rows
                      if r.get("ticker") and str(r.get("type", "stock")).lower() == "stock"})
    if len(tickers) < 400:
        raise RuntimeError(
            f"SPY holdings returned only {len(tickers)} tickers — refusing to shrink the "
            "universe on a partial response. Check the UW plan/endpoint before rerunning."
        )
    return tickers


# The ETFs the strategy trades alongside single names. Not in SPY holdings, so kept
# explicitly — these are instruments, not an opinion about which companies matter.
ETF_SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SMH", "IBB", "KRE", "TLT", "GLD", "SLV", "USO",
    # Liquid non-S&P names the strategy already held; keeping them avoids silently
    # dropping open positions when the universe definition changes.
    "COIN", "MSTR",
]


def unix_date(yyyy_mm_dd):
    dt = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def download(symbol):
    period1 = unix_date("1998-01-01")
    period2 = int(datetime.now(timezone.utc).timestamp())

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?" + urllib.parse.urlencode({
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    })

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 GreyLineHistoricalDownloader/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        print(f"SKIP {symbol}: no Yahoo chart result")
        return False

    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    rows = []

    for i, ts in enumerate(timestamps):
        try:
            o = quote.get("open", [])[i]
            h = quote.get("high", [])[i]
            l = quote.get("low", [])[i]
            c = quote.get("close", [])[i]
            v = quote.get("volume", [])[i]
        except Exception:
            continue

        if None in (o, h, l, c, v):
            continue

        rows.append({
            "date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
            "open": round(float(o), 6),
            "high": round(float(h), 6),
            "low": round(float(l), 6),
            "close": round(float(c), 6),
            "volume": int(v),
        })

    if len(rows) < 2:
        print(f"SKIP {symbol}: no usable rows")
        return False

    out = DATA_DIR / f"{symbol}_daily.csv"

    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"OK {symbol}: {len(rows)} rows -> {out}")
    return True


def main():
    ok = 0
    bad = 0
    skipped = 0

    symbols = sorted(set(sp500_symbols()) | set(ETF_SYMBOLS))
    print(f"universe: {len(symbols)} symbols (S&P 500 constituents + {len(ETF_SYMBOLS)} ETFs)")

    for symbol in symbols:
        # Resumable: an existing file with real history is left alone, so a rerun only
        # fetches what changed in the index.
        existing = DATA_DIR / f"{symbol}_daily.csv"
        if existing.exists() and existing.stat().st_size > 10_000:
            skipped += 1
            continue
        try:
            if download(symbol):
                ok += 1
            else:
                bad += 1
        except Exception as e:
            bad += 1
            print(f"ERROR {symbol}: {e}")
        time.sleep(0.25)

    print({
        "ok": ok,
        "bad": bad,
        "already_had": skipped,
        "symbol_count": len(symbols),
        "data_dir": str(DATA_DIR),
    })


if __name__ == "__main__":
    main()
