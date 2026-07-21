"""Reconstruct sweep_flow and opening_flow historically — the mission's core signal.

These two features are the closest thing GreyLine collects to its literal mission ("detect
the inflow and outflow of institutional money"): sweep_flow is urgent split-across-exchanges
conviction, opening_flow is fresh positioning rather than closing. Every other flow feature
was backfilled to ~245 days; these two were believed forward-only and sat at 3 days, putting
a verdict on the actual mission hypothesis ~3.5 weeks out.

They are NOT forward-only. The earlier dismissal was based on /api/stock/{ticker}/flow-alerts
(no date param). But /api/option-trades/flow-alerts is paginated with an `older_than`
timestamp cursor and walks history — verified reaching 18 days back in 20 pages. So the
per-day sweep/opening imbalance can be reconstructed for the full year.

Reproduces the LIVE computation exactly (UWFlowSignalEngine._alert_flows): for a subset of
alerts, flow = (call_ask_prem - put_ask_prem) / (call_ask_prem + put_ask_prem). Sweeps =
has_sweep; openings = all_opening_trades OR volume_oi_ratio > 1. Getting this even slightly
different would make backfilled and live records incomparable — the trap this whole session
kept finding — so it is validated against the live-collected days before the full run.

Writes one record per (symbol, trading-day) with source=BACKFILL_ALERTS, carrying only
sweep_flow / opening_flow. The grader aggregates by day, so these merge with existing flow
records for the same day and simply populate the two features that were missing.
"""

import json
import time
from datetime import datetime
from pathlib import Path

OUT_DIR = Path("app/data/uw_flow")


class UWSweepOpeningBackfillEngine:

    def __init__(self, provider=None, out_dir=None):
        if provider is None:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            provider = UnusualWhalesProvider()
        self.provider = provider
        from pathlib import Path as _P
        self.out_dir = _P(out_dir) if out_dir else OUT_DIR

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    # ---- the live computation, reproduced exactly -------------------------
    def _flow(self, subset):
        call = sum(self._f(r.get("total_ask_side_prem"))
                   for r in subset if str(r.get("type")).lower() == "call")
        put = sum(self._f(r.get("total_ask_side_prem"))
                  for r in subset if str(r.get("type")).lower() == "put")
        denom = call + put
        return round((call - put) / denom, 4) if denom else None

    def _is_opening(self, r):
        return bool(r.get("all_opening_trades")) or self._f(r.get("volume_oi_ratio")) > 1.0

    def day_flows(self, alerts):
        """{day: (sweep_flow, opening_flow)} from a list of alerts, bucketed by trading day."""
        by_day = {}
        for r in alerts:
            day = str(r.get("created_at") or "")[:10]
            if day:
                by_day.setdefault(day, []).append(r)
        out = {}
        for day, rows in by_day.items():
            sweeps = [r for r in rows if r.get("has_sweep")]
            openings = [r for r in rows if self._is_opening(r)]
            out[day] = (self._flow(sweeps), self._flow(openings))
        return out

    # ---- paging -----------------------------------------------------------
    def _page(self, symbol, older_than=None, limit=200):
        params = {"ticker_symbol": symbol, "limit": limit}
        if older_than:
            params["older_than"] = older_than
        resp = self.provider._get("/api/option-trades/flow-alerts", params=params)
        data = resp.get("data") if isinstance(resp, dict) else resp
        return data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else [])

    def fetch_alerts(self, symbol, until_day, max_pages=400):
        """All flow alerts for `symbol` back to `until_day` (ISO), via the older_than cursor.

        Returns the raw alert list. Stops at until_day, at an empty page, or at max_pages
        (a runaway guard). Cursor is the last row's created_at — the UUID id 500s.
        """
        alerts, cursor, seen_ids = [], None, set()
        for _ in range(max_pages):
            rows = self._page(symbol, cursor)
            if not rows:
                break
            new = [r for r in rows if r.get("id") not in seen_ids]
            if not new:
                break                       # cursor stopped advancing
            for r in new:
                seen_ids.add(r.get("id"))
            alerts.extend(new)
            oldest = str(new[-1].get("created_at") or "")
            cursor = oldest
            if oldest[:10] <= until_day:
                break
        return alerts

    # ---- persistence ------------------------------------------------------
    @staticmethod
    def _existing_days(path):
        """Days that already carry a BACKFILL_ALERTS record, so reruns are idempotent."""
        seen = set()
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    try:
                        r = json.loads(line)
                        if r.get("source") == "BACKFILL_ALERTS":
                            seen.add(str(r.get("ts", ""))[:10])
                    except Exception:
                        pass
        return seen

    def backfill(self, symbols, days=250, progress=None):
        from datetime import timedelta
        until = (datetime.utcnow() - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        written = skipped = 0

        for symbol in symbols:
            path = self.out_dir / f"{str(symbol).upper()}.jsonl"
            have = self._existing_days(path)
            try:
                alerts = self.fetch_alerts(symbol, until)
            except Exception:
                if progress:
                    progress(symbol, written, skipped, error=True)
                continue
            flows = self.day_flows(alerts)
            lines = []
            for day, (sweep, opening) in sorted(flows.items()):
                if day in have or (sweep is None and opening is None):
                    skipped += 1
                    continue
                rec = {"ts": f"{day}T20:00:00", "symbol": str(symbol).upper(),
                       "source": "BACKFILL_ALERTS"}
                if sweep is not None:
                    rec["sweep_flow"] = sweep
                if opening is not None:
                    rec["opening_flow"] = opening
                lines.append(json.dumps(rec))
                written += 1
            if lines:
                with path.open("a") as f:
                    f.write("\n".join(lines) + "\n")
            if progress:
                progress(symbol, written, skipped)

        return {"timestamp": datetime.utcnow().isoformat(),
                "engine": "UWSweepOpeningBackfillEngine",
                "symbols": len(list(symbols)), "written": written,
                "already_had": skipped, "status": "SWEEP_OPENING_BACKFILL_COMPLETE"}
