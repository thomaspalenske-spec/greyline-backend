from datetime import date, datetime, timezone
from pathlib import Path
import csv
import time
import urllib.request
import urllib.parse
import json


DATA_DIR = Path("app/data/historical")
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "AMD",
    "JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "AXP",
    "XOM", "CVX", "COP", "SLB", "EOG",
    "UNH", "LLY", "JNJ", "MRK", "PFE", "ABBV", "TMO", "ABT", "DHR",
    "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE",
    "NFLX", "DIS", "CMCSA", "ADBE", "CRM", "ORCL", "INTC", "CSCO", "QCOM", "TXN",
    "BA", "CAT", "DE", "HON", "GE", "LMT", "RTX", "NOC",
    "KO", "PEP", "PG", "PM", "MO", "CL",
    "NEE", "DUK", "SO", "AEP",
    "PLTR", "SNOW", "SHOP", "UBER", "ABNB", "COIN", "MSTR",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    "SMH", "IBB", "KRE", "TLT", "GLD", "SLV", "USO"
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

    for symbol in SYMBOLS:
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
        "symbol_count": len(SYMBOLS),
        "data_dir": str(DATA_DIR),
    })


if __name__ == "__main__":
    main()
