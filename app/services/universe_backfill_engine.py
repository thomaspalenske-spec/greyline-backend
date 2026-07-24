"""Backfill daily history for newly-added universe names, in the exact on-disk format.

Companion to UniverseExpansionEngine: that one decides WHICH liquid names to add, this one
fetches their history so they can be signalled and backtested. TradeStation barcharts serve
6,000 daily bars (verified back to 2002), which is well past the 253 the 12-1 signal needs and
deep enough for real backtests — so a new name is not a second-class citizen.

WRITES ARE THE POINT OF CARE. These files ARE the signal foundation (the "live" universe is
disk history + today's quote tip), so:
  * format matches byte-for-byte: date,open,high,low,close,volume, oldest-first
  * a symbol is written ONLY if the fetch returned a plausible series; a short/garbage
    response never overwrites or creates a file
  * existing files are never touched unless overwrite=True — backfill is additive by default
  * idempotent and resumable: already-present symbols are skipped, so a interrupted run can
    simply be re-run

Rate: TradeStation caps near 2 req/s, so ~358 names take a few minutes. `limit` exists to
sample a handful first and confirm the shape before committing to the full run.
"""

import csv
import time
from datetime import datetime
from os import getenv
from pathlib import Path

import requests


class UniverseBackfillEngine:

    HIST_DIR = Path("app/data/historical")
    BARS_BACK = 6000          # verified available (to ~2002); 253 needed to signal
    # A recent IPO genuinely HAS a short history — that is reality, not a defect, and
    # excluding it would be the same quality-screen error as the old liquidity gate. The
    # signal engine's own MIN_BARS=253 decides eligibility at DECISION time, and the name
    # becomes selectable naturally as it matures. This floor only rejects responses too
    # small to be a real series at all (distinct from the pre-listing STUB problem, which
    # was years of fake near-zero-volume prints, not an honestly short history).
    MIN_ACCEPTABLE_BARS = 20
    SLEEP_SECONDS = 1.1        # ~0.9 req/s — 0.5s got throttled on a 7k-name run

    def _token(self, force=False):
        try:
            from app.services.tradestation_token_maintenance_engine import (
                TradeStationTokenMaintenanceEngine)
            TradeStationTokenMaintenanceEngine().evaluate()
        except Exception:
            pass
        return getenv("TRADESTATION_ACCESS_TOKEN", "")

    MAX_RETRIES = 4
    BACKOFF_BASE = 3.0        # seconds; doubles per retry

    def _fetch(self, symbol, token, base):
        """Fetch with exponential backoff.

        A first attempt at this ran with no retry logic: TradeStation throttled after ~750
        rapid requests and the loop kept hammering at the same rate, so 6,381 of 6,976 names
        "failed" when the API was perfectly healthy. Transient throttling must be waited out,
        not counted as a permanent failure — otherwise a long backfill silently mangles the
        universe it is supposed to be building.
        """
        url = f"{base.rstrip('/')}/v3/marketdata/barcharts/{symbol}"
        r = None
        for attempt in range(self.MAX_RETRIES):
            try:
                r = requests.get(url, params={"unit": "Daily", "barsback": self.BARS_BACK},
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/json"}, timeout=40)
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    return None, f"network: {str(e)[:50]}"
                time.sleep(self.BACKOFF_BASE * (2 ** attempt))
                continue
            # 401 = the access token expired MID-RUN. This is the failure that silently
            # destroyed a 7,000-name backfill: ~1,800 consecutive names "failed" while every
            # one of them fetched perfectly when retried with a fresh token. Refresh and retry
            # — never count an auth lapse as a permanent per-symbol failure.
            if r.status_code == 401:
                token = self._token(force=True)
                if attempt == self.MAX_RETRIES - 1:
                    return None, "HTTP 401 (token refresh failed)"
                time.sleep(1.0)
                continue
            # 429 = rate limited, 5xx = transient server. Both are wait-and-retry, not failure.
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.MAX_RETRIES - 1:
                    return None, f"HTTP {r.status_code} after {self.MAX_RETRIES} retries"
                time.sleep(self.BACKOFF_BASE * (2 ** attempt))
                continue
            break
        if r is None or r.status_code != 200:
            return None, f"HTTP {r.status_code if r is not None else '?'}"
        bars = (r.json() or {}).get("Bars") or []
        rows = []
        for b in bars:
            ts = b.get("TimeStamp") or b.get("Timestamp")
            try:
                o, h, l, c = (float(b["Open"]), float(b["High"]),
                              float(b["Low"]), float(b["Close"]))
                v = float(b.get("TotalVolume") or b.get("Volume") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if not ts or min(o, h, l, c) <= 0:
                continue
            rows.append((str(ts)[:10], o, h, l, c, v))
        rows.sort(key=lambda x: x[0])
        return rows, None

    def _write(self, symbol, rows):
        path = self.HIST_DIR / f"{symbol}_daily.csv"
        tmp = path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "high", "low", "close", "volume"])
            for d, o, h, l, c, v in rows:
                w.writerow([d, o, h, l, c, int(v)])
        tmp.replace(path)          # atomic: never leave a half-written signal file
        return path

    def backfill(self, symbols, overwrite=False, limit=None):
        token = self._token()
        base = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        if not token:
            return {"status": "NO_TRADESTATION_TOKEN", "written": 0}

        syms = [str(s).upper() for s in (symbols or [])]
        if limit:
            syms = syms[:int(limit)]

        written, skipped_existing, failed, too_short = [], [], [], []
        REFRESH_EVERY = 100        # tokens expire on long runs; refresh well inside the window
        for n, sym in enumerate(syms):
            if n and n % REFRESH_EVERY == 0:
                token = self._token(force=True)
            path = self.HIST_DIR / f"{sym}_daily.csv"
            if path.exists() and not overwrite:
                skipped_existing.append(sym)
                continue
            try:
                rows, err = self._fetch(sym, token, base)
            except Exception as e:
                failed.append({"symbol": sym, "error": str(e)[:70]})
                time.sleep(self.SLEEP_SECONDS)
                continue
            if err or rows is None:
                failed.append({"symbol": sym, "error": err or "no data"})
            elif len(rows) < self.MIN_ACCEPTABLE_BARS:
                # not a usable series at all (not a judgement about the company)
                too_short.append({"symbol": sym, "bars": len(rows)})
            else:
                self._write(sym, rows)
                written.append({"symbol": sym, "bars": len(rows),
                                "first": rows[0][0], "last": rows[-1][0]})
            time.sleep(self.SLEEP_SECONDS)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "requested": len(syms),
            "written": len(written),
            "skipped_existing": len(skipped_existing),
            "too_short": too_short[:20],
            "too_short_count": len(too_short),
            "failed": failed[:20],
            "failed_count": len(failed),
            "sample_written": written[:8],
            "status": "UNIVERSE_BACKFILL_COMPLETE",
        }
