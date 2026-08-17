"""Prove the on-disk price bars match an INDEPENDENT source — TradeStation's own barcharts.

`price_bar_integrity_engine` checks the CSVs against THEMSELVES: impossible OHLC, duplicate
closes, frozen runs. Self-consistency cannot detect data that is uniformly wrong — a series
shifted, scaled, mis-mapped to another ticker, or carrying an unadjusted split is perfectly
self-consistent and completely false. Only a second source can catch that.

This matters more than it looks. `_live_universe` does NOT fetch independent history: it
builds the series from these CSVs and appends only today's quote as the tip. So the CSVs are
the foundation of every 12-1 momentum signal, every ATR, and therefore every stop and every
take-profit the doctrine places. "TRADESTATION_LIVE" means CSV history + one live bar.

An unadjusted split is caught here for free: TradeStation's bars are adjusted, so a split the
CSV missed shows up as a deviation clustering near an exact ratio (0.5, 0.25, 2.0...). That
is empirical detection from real data, not the ratio GUESS the integrity scanner has to make.

Coverage is a ROTATING sample: TradeStation rate-limits near 2 req/s, so scanning all 557
symbols every day would be slow and API-hungry. A cursor advances each run, so the whole
universe is covered over a couple of weeks while any single run stays cheap.
"""

import csv
import json
import os
from datetime import datetime
from pathlib import Path


class PriceBarCrossSourceEngine:

    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/data_quality/price_bar_cross_source.json")
    STATE = Path("app/data/data_quality/cross_source_cursor.json")

    SAMPLE_SIZE = 40          # symbols per run (~20s at TradeStation's ~2 req/s)
    COMPARE_DAYS = 120        # recent overlap to compare — the window signals actually use
    TOLERANCE_PCT = 0.10      # above float-rounding noise (observed max 0.03%), below real error
    MAX_BAD_DAYS = 2          # isolated stale prints happen; a systematic break does not
    SCAN_INTERVAL_HOURS = 24

    # A deviation ratio landing on one of these is the signature of a split the CSV missed.
    SPLIT_RATIOS = (0.5, 1 / 3, 0.25, 2 / 3, 0.75, 2.0, 3.0, 4.0)

    def _csv_closes(self, symbol):
        out = {}
        try:
            with open(self.HIST_DIR / f"{symbol}_daily.csv") as f:
                for r in csv.DictReader(f):
                    try:
                        out[str(r["date"])[:10]] = float(r["close"])
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return {}
        return out

    def _symbols(self):
        return sorted(p.name.replace("_daily.csv", "")
                      for p in self.HIST_DIR.glob("*_daily.csv"))

    def _next_batch(self, symbols, size):
        """Rotate through the universe so repeated runs eventually cover everything."""
        start = 0
        try:
            start = int(json.loads(self.STATE.read_text()).get("cursor") or 0)
        except Exception:
            pass
        if not symbols:
            return [], 0
        start %= len(symbols)
        batch = (symbols + symbols)[start:start + size]
        nxt = (start + size) % len(symbols)
        try:
            self.STATE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps({"cursor": nxt,
                                              "updated_at": datetime.utcnow().isoformat()}))
        except Exception:
            pass
        return batch, start

    def _split_like(self, ratio):
        return any(abs(ratio - r) < 0.02 for r in self.SPLIT_RATIOS)

    def reconcile(self, symbols=None, sample=None, save=True):
        from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
        from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine

        universe = self._symbols()
        if symbols:
            batch, cursor = [s.upper() for s in symbols], None
        else:
            batch, cursor = self._next_batch(universe, int(sample or self.SAMPLE_SIZE))

        try:
            TradeStationTokenMaintenanceEngine().evaluate()
        except Exception:
            pass
        token = os.getenv("TRADESTATION_ACCESS_TOKEN", "") or ""
        base = os.getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        if not token:
            return {"timestamp": datetime.utcnow().isoformat(), "checked": 0,
                    "status": "CROSS_SOURCE_NO_TOKEN", "ok": None,
                    "detail": "no TradeStation access token — cannot reach the second source"}

        fetcher = MomentumReversalStrategyEngine()
        results, mismatches, unreachable = [], [], []

        for sym in batch:
            try:
                live = dict(fetcher._fetch_daily_closes(sym, base, token))
            except Exception as e:
                unreachable.append({"symbol": sym, "error": str(e)[:100]})
                continue
            ours = self._csv_closes(sym)
            common = sorted(set(live) & set(ours))[-self.COMPARE_DAYS:]
            if not common:
                unreachable.append({"symbol": sym, "error": "no overlapping dates"})
                continue

            bad, worst, ratios = [], 0.0, []
            for d in common:
                a, b = ours[d], live[d]
                if not b:
                    continue
                dev = abs(a - b) / b * 100
                worst = max(worst, dev)
                if dev > self.TOLERANCE_PCT:
                    bad.append({"date": d, "ours": a, "source": b, "deviation_pct": round(dev, 3)})
                    ratios.append(a / b)

            rec = {"symbol": sym, "days_compared": len(common),
                   "max_deviation_pct": round(worst, 3), "bad_days": len(bad)}
            if len(bad) > self.MAX_BAD_DAYS:
                # Many days off by the SAME ratio = a corporate action the CSV never applied,
                # not random noise. Naming that is far more actionable than "prices differ".
                med = sorted(ratios)[len(ratios) // 2] if ratios else 0
                rec["verdict"] = ("UNADJUSTED_SPLIT_SUSPECTED" if self._split_like(med)
                                  else "SYSTEMATIC_MISMATCH")
                rec["median_ratio"] = round(med, 4)
                rec["examples"] = bad[:5]
                mismatches.append(rec)
            else:
                rec["verdict"] = "MATCH"
            results.append(rec)

        checked = len(results)
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "TRADESTATION_BARCHARTS",
            "universe_size": len(universe),
            "cursor_started_at": cursor,
            "checked": checked,
            "compared_days_each": self.COMPARE_DAYS,
            "tolerance_pct": self.TOLERANCE_PCT,
            "matched": checked - len(mismatches),
            "mismatched": len(mismatches),
            "mismatches": mismatches,
            "unreachable": unreachable,
            "results": results,
            "ok": len(mismatches) == 0,
            "status": ("PRICE_BARS_CROSS_SOURCE_VERIFIED" if not mismatches
                       else "PRICE_BARS_CROSS_SOURCE_MISMATCH"),
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def reconcile_if_due(self, hours=None, sample=None):
        """Self-gating so the scheduler can call this every cycle for ~one run a day."""
        # Explicit None check: `hours or DEFAULT` would turn an intentional hours=0
        # ("reconcile now") into the 24h default and make a forced run impossible.
        hours = self.SCAN_INTERVAL_HOURS if hours is None else float(hours)
        prev = self.last_run()
        if prev:
            try:
                age_h = (datetime.utcnow()
                         - datetime.fromisoformat(prev["timestamp"])).total_seconds() / 3600.0
                if age_h < hours:
                    return {"status": "CROSS_SOURCE_NOT_DUE", "ran": False,
                            "hours_since_last": round(age_h, 2),
                            "last_status": prev.get("status"),
                            "last_mismatched": prev.get("mismatched")}
            except Exception:
                pass
        res = self.reconcile(sample=sample)
        res["ran"] = True
        return res

    def last_run(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
