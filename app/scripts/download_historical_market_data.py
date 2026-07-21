from datetime import date, datetime, timezone
from pathlib import Path
import csv
import time
import urllib.request
import urllib.parse
import json


DATA_DIR = Path("app/data/historical")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def _index_holdings(etf, min_expected):
    """Current constituents of an index, from its tracking ETF's holdings (Unusual Whales).

    Sourcing the universe from live holdings replaces a hand-typed list —
    MomentumReversalStrategyEngine._symbols() globs the CSVs this writes, so whatever lands
    here IS what the strategy may select. `min_expected` guards against a partial API
    response silently shrinking the universe.
    """
    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider

    resp = UnusualWhalesProvider()._get(f"/api/etfs/{etf}/holdings", params={"limit": 600})
    rows = (resp.get("data") if isinstance(resp, dict) else resp) or []
    tickers = sorted({r.get("ticker") for r in rows
                      if r.get("ticker") and str(r.get("type", "stock")).lower() == "stock"})
    if len(tickers) < min_expected:
        raise RuntimeError(
            f"{etf} holdings returned only {len(tickers)} tickers (expected >= {min_expected}) "
            "— refusing to shrink the universe on a partial response. Check the UW endpoint."
        )
    return tickers


def sp500_symbols():
    """The ~504 S&P 500 constituents (500 companies, plus dual classes like GOOG/GOOGL)."""
    return _index_holdings("SPY", min_expected=400)


def dow_symbols():
    """The 30 Dow Jones Industrial Average constituents (DIA holdings).

    Every Dow name is CURRENTLY also an S&P 500 member, so this is a subset of
    sp500_symbols() today. It is pinned explicitly anyway because the two indices are
    maintained by DIFFERENT committees: were a Dow component ever dropped from the S&P
    500, sourcing the universe from SPY holdings alone would silently drop it from what
    GreyLine can trade. Unioning DIA guarantees the Dow is always tradable regardless.
    """
    return _index_holdings("DIA", min_expected=25)


# ETFs the strategy trades alongside single names — instruments, not an opinion about
# which companies matter. This is how a $10k CASH-equity account gets futures, commodity,
# rate and international exposure: through liquid, cash-settled, whole-share-sizable
# trackers the existing pipeline handles cleanly. It is deliberately NOT leveraged/inverse
# or volatility-decay products (UVXY, UNG-style contango traps as core holdings) — those
# adversely select under a momentum signal. Every name here is an established, liquid ETF.
ETF_SYMBOLS = [
    # Broad equity beta
    "SPY", "QQQ", "IWM", "DIA", "VTI",
    # US sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SMH", "IBB", "KRE",
    # --- COMMODITIES (the "commodity market", via liquid futures-backed trackers) ---
    "DBC",   # broad commodity basket
    "DBA",   # agriculture
    "GLD", "SLV", "USO",
    "UNG",   # natural gas
    "CPER",  # copper
    "PPLT",  # platinum
    # --- RATES / BONDS (the Treasury + credit "market") ---
    "TLT",   # 20y+ Treasuries
    "IEF",   # 7-10y Treasuries
    "SHY",   # 1-3y Treasuries
    "AGG",   # aggregate bond
    "LQD",   # investment-grade credit
    "HYG",   # high-yield credit
    "TIP",   # inflation-protected
    # --- INTERNATIONAL EQUITY (the ex-US "markets") ---
    "EFA",   # developed ex-US
    "EEM",   # emerging markets
    "VWO",   # emerging markets (Vanguard)
    "FXI",   # China large-cap
    "EWJ",   # Japan
    "EWZ",   # Brazil
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

    sp500 = set(sp500_symbols())
    dow = set(dow_symbols())
    symbols = sorted(sp500 | dow | set(ETF_SYMBOLS))
    dow_only = sorted(dow - sp500)
    print(f"universe: {len(symbols)} symbols (S&P 500 + {len(dow)} Dow + {len(ETF_SYMBOLS)} ETFs)")
    print(f"  Dow components not in the S&P 500 (pinned so they can't drop): "
          f"{dow_only if dow_only else 'none today — all 30 are S&P members'}")

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
