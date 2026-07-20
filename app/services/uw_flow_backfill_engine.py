"""Reconstruct historical institutional-flow records from Unusual Whales' dated endpoints.

The mission rests on stage 2 — does institutional flow predict price — and the grader
refuses a verdict below 20 distinct days. Collected forward, the series was 8 days deep and
the four features that read institutional money most directly (dark pool, OI change, sweeps,
openings) started accumulating on 2026-07-19, putting a real verdict a month out.

Most UW flow endpoints accept a `date`, and they return full depth for every trading day
going back at least a year (verified: flow-per-strike ~370-400 rows/day, greek-exposure
~250, darkpool 200, oi-change 50, with no entitlement 403s). So the 20-day gate does not
have to be waited out — it can be reconstructed.

THREE CORRECTNESS RULES, because a subtly wrong backfill is worse than no backfill:

1. SAME EXTRACTION. Backfilled records are built by handing a synthetic snapshot to
   UWFlowSignalEngine.extract() — the identical code the live path runs. Reimplementing the
   feature maths here would let backfilled and live records diverge silently.

2. NEVER _enrich(). UWFlowSignalEngine._enrich() fetches dark pool, OI and alerts from
   UNDATED endpoints — i.e. today's data. Calling it while writing a record stamped
   2026-06-15 would staple June's flow to July's institutional positioning: contamination
   that would look like predictive power. The dated equivalents are attached here instead.

3. SWEEPS AND OPENINGS ARE NOT BACKFILLABLE. /api/stock/{t}/flow-alerts takes only `limit`,
   no date, so sweep_flow and opening_flow cannot be reconstructed and are deliberately
   absent from backfilled records. The grader treats a missing feature as no observation, so
   they simply keep accumulating forward. Faking them from undated alerts is exactly the
   contamination rule 2 forbids.

Every record is stamped source=BACKFILL so live and reconstructed observations stay
distinguishable forever.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from app.services.uw_flow_signal_engine import UWFlowSignalEngine

OUT_DIR = Path("app/data/uw_flow")


class UWFlowBackfillEngine:

    def __init__(self, provider=None):
        if provider is None:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            provider = UnusualWhalesProvider()
        self.provider = provider
        self.signal = UWFlowSignalEngine()

    # ---- provider plumbing -------------------------------------------------
    def _get(self, path, **params):
        try:
            return self.provider._get(path, params=params)
        except Exception:
            return None

    @staticmethod
    def _rows(resp):
        if isinstance(resp, dict):
            return resp.get("data") or []
        return resp or []

    # The endpoints are read from the provider's own path map, NOT hardcoded, so a
    # backfilled record is built from exactly the source the live snapshot uses. Getting
    # this wrong is silent, not loud: /greek-exposure returns call_gamma while
    # /greek-exposure/strike returns call_gex, so the wrong one yields dealer_gex = 0.0
    # rather than an error — a zeroed feature that would quietly dilute the grade. Same
    # trap on flow: /flow-per-strike has no net_premium field, /flow-per-strike-intraday
    # does. Both bugs were caught by comparing a reconstructed day against a live one.
    SNAPSHOT_SIGNALS = (
        "flow_per_strike_intraday",
        "greek_exposure_by_strike",
        "historical_risk_reversal_skew",
    )

    def _path_for(self, key, symbol):
        template = self.provider.OBSERVATION_ONLY_ENDPOINTS[key]
        return template.replace("{ticker}", symbol).replace("{symbol}", symbol)

    def _snapshot(self, symbol, day):
        """A synthetic snapshot in the shape UWFlowSignalEngine.extract() expects, built
        entirely from DATED calls so every component describes the same historical day."""
        iso = day.isoformat()
        signals = {key: self._get(self._path_for(key, symbol), date=iso)
                   for key in self.SNAPSHOT_SIGNALS}
        return {"symbol": symbol,
                # extract() reads the snapshot timestamp; it must be the historical day,
                # never now, or the grader would score this against the wrong forward bar.
                "timestamp": f"{iso}T20:00:00",
                "providers": {"UNUSUAL_WHALES": {"signals": signals}}}

    # ---- dated equivalents of _enrich() ------------------------------------
    def _dark_pool_flow(self, symbol, day):
        rows = self._rows(self._get(f"/api/darkpool/{symbol}", date=day.isoformat(), limit=200))
        buy = sell = 0.0
        for r in rows:
            if r.get("canceled"):
                continue
            try:
                price = float(r["price"]); bid = float(r["nbbo_bid"]); ask = float(r["nbbo_ask"])
            except (TypeError, ValueError, KeyError):
                continue
            prem = self.signal._f(r.get("premium"))
            mid = (bid + ask) / 2
            if price > mid:
                buy += prem
            elif price < mid:
                sell += prem
        denom = buy + sell
        return round((buy - sell) / denom, 4) if denom else None

    def _oi_flow(self, symbol, day):
        rows = self._rows(self._get(f"/api/stock/{symbol}/oi-change", date=day.isoformat(), limit=200))
        call = put = 0.0
        for r in rows:
            m = self.signal._OPT_TYPE.search(str(r.get("option_symbol") or ""))
            if not m:
                continue
            v = self.signal._f(r.get("oi_change") if r.get("oi_change") is not None
                               else r.get("oi_diff_plain"))
            if m.group(1) == "C":
                call += v
            else:
                put += v
        denom = abs(call) + abs(put)
        return round((call - put) / denom, 4) if denom else None

    # ---- one day ------------------------------------------------------------
    def build_record(self, symbol, day):
        """A flow record for (symbol, day), or None if UW has no usable flow that day."""
        rec = self.signal.extract(self._snapshot(symbol, day))
        if not rec:
            return None
        dp = self._dark_pool_flow(symbol, day)
        if dp is not None:
            rec["dark_pool_flow"] = dp
        oi = self._oi_flow(symbol, day)
        if oi is not None:
            rec["oi_flow"] = oi
        # sweep_flow / opening_flow intentionally absent — see rule 3.
        rec["source"] = "BACKFILL"
        return rec

    # ---- persistence --------------------------------------------------------
    @staticmethod
    def _existing_ts(path):
        if not path.exists():
            return set()
        out = set()
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.add(json.loads(line).get("ts"))
                except Exception:
                    pass
        return out

    def backfill(self, symbols, days=60, end=None, progress=None):
        """Reconstruct `days` trading days back from `end` for each symbol. Idempotent:
        a timestamp already present is skipped, so reruns cost nothing and never duplicate."""
        end = end or date.today()
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        written = skipped = empty = 0

        for symbol in symbols:
            path = OUT_DIR / f"{str(symbol).upper()}.jsonl"
            seen = self._existing_ts(path)
            lines = []
            cursor, remaining = end, days
            while remaining > 0:
                cursor -= timedelta(days=1)
                if cursor.weekday() >= 5:      # UW returns nothing on weekends
                    continue
                remaining -= 1
                rec = self.build_record(symbol, cursor)
                if not rec:
                    empty += 1
                    continue
                if rec["ts"] in seen:
                    skipped += 1
                    continue
                lines.append(json.dumps(rec))
                written += 1
            if lines:
                with path.open("a") as f:
                    f.write("\n".join(lines) + "\n")
            if progress:
                progress(symbol, written, skipped, empty)

        return {"timestamp": datetime.utcnow().isoformat(),
                "engine": "UWFlowBackfillEngine", "symbols": len(list(symbols)),
                "days_requested": days, "written": written, "already_had": skipped,
                "no_data": empty, "status": "UW_FLOW_BACKFILL_COMPLETE"}
