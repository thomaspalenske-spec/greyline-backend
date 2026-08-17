"""Quantify the survivorship bias in GreyLine's history — turn an unbounded fear into a number.

GreyLine's price universe is today's listed names applied backward: every company that
delisted is simply absent. `UniverseSurvivorshipEngine` fixes this GOING FORWARD (it retains
names as they leave). This engine measures the damage ALREADY BAKED IN — how big the hole is
in the historical data — using UW's authoritative listings feed (ticker, ipo_date,
delisting_date for 5,983 real NYSE/NASDAQ stocks).

WHAT IT CAN AND CANNOT SAY, honestly:

  CAN: the DISAPPEARANCE RATE. Of the stocks trading at the start of a window, what fraction
  had delisted (vanished from a survivor-only universe) by the end. ~3.8%/yr of the broad
  investable universe over 2015-2026.

  CANNOT: the exact RETURN bias. That depends on WHY each name delisted, and UW carries no
  reason field:
    * ACQUISITION / merger — you would have realised the deal price. NOT a return you missed;
      a survivor-only backtest is barely biased by these. For LARGE CAPS this is the dominant
      mode.
    * FAILURE / bankruptcy — you would have ridden it toward zero. A survivor-only backtest
      silently skips that loss and overstates returns. This is the real bias.
  The raw disappearance rate is therefore an UPPER BOUND on "names missing", not the return
  overstatement. Academic estimates put large-cap survivorship bias at ~+1-2%/yr of overstated
  return; small-cap/broad universes higher. We report the measured rate and refuse to invent a
  precise return number we cannot support.

DATA TRAP HANDLED: UW stamps a batch of recently-inactive tickers with a near-snapshot date
(368 on 2026-07-17, two days before the fetch — implausible vs ~30-40 on real busy days). Any
delisting inside `ARTIFACT_LAG_DAYS` of the snapshot is excluded as unreliable.
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path


class SurvivorshipBiasEngine:

    LISTINGS = Path("app/data/research/universe/uw_listings_snapshot.json")
    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/research/survivorship_bias_report.json")

    ARTIFACT_LAG_DAYS = 90        # delistings this close to the snapshot are batch-flag noise
    SEASONED_MIN_YEARS = 8        # listed at least this long ≈ established, large-cap-like

    def _d10(self, x):
        x = str(x or "")
        return x[:10] if x.lower() not in ("null", "none", "") else None

    def _real_stock(self, r):
        return (str(r.get("asset_type")) == "Stock"
                and str(r.get("exchange")) in ("NYSE", "NASDAQ")
                and not any(x in str(r.get("ticker", "")) for x in ("-WS", "-U", "-P", "-W", ".")))

    def _load(self):
        try:
            snap = json.loads(self.LISTINGS.read_text())
        except Exception:
            return None, None, []
        fetched = str(snap.get("fetched_at") or "")[:10] or None
        artifact_cutoff = None
        if fetched:
            try:
                artifact_cutoff = (datetime.fromisoformat(fetched).date()
                                   - timedelta(days=self.ARTIFACT_LAG_DAYS)).isoformat()
            except Exception:
                artifact_cutoff = None
        stocks = [r for r in (snap.get("listings") or []) if self._real_stock(r)]
        return fetched, artifact_cutoff, stocks

    def _years_listed(self, r):
        ipo, dl = self._d10(r.get("ipo_date")), self._d10(r.get("delisting_date"))
        if not ipo or not dl:
            return None
        return (int(dl[:4]) + int(dl[5:7]) / 12) - (int(ipo[:4]) + int(ipo[5:7]) / 12)

    def _current_universe(self):
        return {p.name.replace("_daily.csv", "") for p in self.HIST_DIR.glob("*_daily.csv")}

    def measure(self, start, end, stocks=None, artifact_cutoff=None, universe=None):
        """Disappearance rate over [start, end], with a seasoned (large-cap-like) subset."""
        if stocks is None:
            _, artifact_cutoff, stocks = self._load()
        universe = universe if universe is not None else self._current_universe()

        def in_window_delist(r):
            dl = self._d10(r.get("delisting_date")) or "2100"
            if not (start < dl <= end):
                return False
            if artifact_cutoff and dl >= artifact_cutoff:   # exclude batch-flag noise
                return False
            return True

        listed_at_start = [r for r in stocks
                           if (self._d10(r.get("ipo_date")) or "1900") <= start
                           and (self._d10(r.get("delisting_date")) or "2100") > start]
        disappeared = [r for r in listed_at_start if in_window_delist(r)]

        def seasoned(r):
            return (self._years_listed(r) or 0) >= self.SEASONED_MIN_YEARS \
                or (self._d10(r.get("ipo_date")) or "9999") < "2007-01-01"
        seasoned_start = [r for r in listed_at_start if seasoned(r)]
        seasoned_gone = [r for r in disappeared if seasoned(r)]

        try:
            yrs = (int(end[:4]) + int(end[5:7]) / 12) - (int(start[:4]) + int(start[5:7]) / 12)
        except Exception:
            yrs = None
        absent = [r for r in disappeared if r.get("ticker") not in universe]
        rate = len(disappeared) / len(listed_at_start) * 100 if listed_at_start else 0.0
        srate = len(seasoned_gone) / len(seasoned_start) * 100 if seasoned_start else 0.0

        return {
            "window": [start, end],
            "years": round(yrs, 2) if yrs else None,
            "listed_at_start": len(listed_at_start),
            "disappeared": len(disappeared),
            "disappearance_rate_pct": round(rate, 1),
            "annualized_disappearance_pct": round(rate / yrs, 2) if yrs else None,
            "absent_from_greyline_universe": len(absent),
            "seasoned_listed_at_start": len(seasoned_start),
            "seasoned_disappeared": len(seasoned_gone),
            "seasoned_disappearance_rate_pct": round(srate, 1),
            "sample_absent": [
                {"ticker": r.get("ticker"), "name": str(r.get("name"))[:44],
                 "delisted": self._d10(r.get("delisting_date"))}
                for r in sorted(seasoned_gone,
                                key=lambda r: self._d10(r.get("delisting_date")) or "", reverse=True)[:12]
            ],
        }

    def assess(self, save=True):
        fetched, artifact_cutoff, stocks = self._load()
        if not stocks:
            return {"status": "NO_LISTINGS_SNAPSHOT", "ok": None,
                    "detail": "UW listings snapshot unavailable — cannot quantify survivorship bias"}
        universe = self._current_universe()
        # end windows before the artifact zone so the headline rate isn't inflated by batch noise
        end = artifact_cutoff or "2026-04-01"
        windows = [self.measure(s, end, stocks, artifact_cutoff, universe)
                   for s in ("2010-01-01", "2015-01-01", "2020-01-01")]

        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "UW_LISTINGS_SNAPSHOT",
            "snapshot_fetched": fetched,
            "artifact_cutoff": artifact_cutoff,
            "real_stocks_tracked": len(stocks),
            "greyline_universe": len(universe),
            "windows": windows,
            "interpretation": {
                "measured": "disappearance rate — fraction of stocks trading at window-start "
                            "that had delisted (vanished from a survivor-only universe) by window-end",
                "is_an_upper_bound": "the raw rate bounds NAMES MISSING, not the return "
                                     "overstatement. Acquisitions (dominant for large caps) are "
                                     "captured at the deal price, not a return you missed; only "
                                     "failures bias a survivor-only backtest.",
                "cannot_measure": "exact return bias — UW carries no delisting REASON, so "
                                  "acquisition vs failure cannot be separated from this feed. "
                                  "Large-cap survivorship bias is academically ~+1-2%/yr.",
                "unfixable_for_free": "delisted-company PRICES are needed to actually include "
                                      "these names; TradeStation and UW both return empty for "
                                      "them. Only a survivorship-free vendor (CRSP/Norgate/"
                                      "Sharadar) closes it.",
            },
            "status": "SURVIVORSHIP_BIAS_QUANTIFIED",
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def headline(self):
        """One-line magnitude for other engines to cite in their bias declarations."""
        rep = self.last_report() or self.assess()
        w = next((x for x in (rep.get("windows") or []) if x["window"][0] == "2015-01-01"), None)
        if not w:
            return None
        return {
            "since": w["window"][0],
            "disappearance_rate_pct": w["disappearance_rate_pct"],
            "annualized_pct": w["annualized_disappearance_pct"],
            "note": "raw disappearance rate (upper bound on missing names, not return bias)",
        }

    def last_report(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
