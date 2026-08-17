"""Earnings implied-vs-realized move — the first candidate that can actually pay for options.

Everything GreyLine has tested (informed flow, mechanical flow, PEAD, momentum-reversal) failed
the ECONOMIC MAGNITUDE screen long before it failed a significance test: those are sub-2%
phenomena, and an OTM option round-trip costs 500-1500bps of premium. They were never the right
size class, whatever their p-values.

Earnings moves are. Measured across 70,322 historical announcements on our own bars:
    median 3.43% | mean 5.04% | p75 6.63% | p90 11.23%
    28.7% of events move >= 6%, the OTM-viable threshold.

And the trade does not require predicting DIRECTION — only that the options market misprices
the MAGNITUDE. That is options-native (it is the variance risk premium applied to an event),
and every earnings announcement is a clean natural experiment with a known date.

WHY THIS MUST BE FORWARD-TESTED, NOT BACKTESTED:
The realized side is measurable from history — done above. The IMPLIED side is not: UW's
historic-contract endpoint returns zero rows and TradeStation purges expired contracts, so
there is no way to know what the market charged for an earnings move in 2015. Any "backtest" of
this would be fabricated. So this engine records the implied move BEFORE each announcement and
the realized move AFTER, building the comparison honestly from today forward. With ~1,500
covered names reporting quarterly, a meaningful sample accrues within a quarter.

WHAT WOULD CONSTITUTE AN EDGE:
  implied systematically ABOVE realized -> options overprice earnings -> selling premium pays
  implied systematically BELOW realized -> options underprice -> buying premium pays
Neither is assumed. The engine records both sides and reports the spread; the verdict comes
from the accumulated panel, not from a prior.
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path


class EarningsVolEdgeEngine:

    EARN_DIR = Path("app/data/earnings")
    PRICE_DIR = Path("app/data/historical_total_return")
    SURFACE_DIR = Path("app/data/options_reality")
    OUT = Path("app/data/research/earnings_vol_panel.jsonl")

    LOOKAHEAD_DAYS = 8      # capture implied for announcements this far out
    MIN_IMPLIED_PCT = 0.0

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _upcoming_earnings(self, days=None):
        """{ticker: report_date} for announcements inside the lookahead window."""
        days = days or self.LOOKAHEAD_DAYS
        today = datetime.utcnow().date()
        horizon = (today + timedelta(days=days)).isoformat()
        today_s = today.isoformat()
        out = {}
        for p in self.EARN_DIR.glob("*.json"):
            try:
                rows = json.loads(p.read_text())
            except Exception:
                continue
            for r in rows or []:
                d = str(r.get("report_date") or "")[:10]
                if today_s <= d <= horizon:
                    out[p.stem] = d
                    break
        return out

    def _latest_surface(self):
        """Most recent captured options surface, keyed by ticker."""
        try:
            files = sorted(self.SURFACE_DIR.glob("options_surface_*.jsonl"))
        except Exception:
            files = []
        if not files:
            return {}, None
        latest = files[-1]
        day = latest.name.replace("options_surface_", "").replace(".jsonl", "")
        surf = {}
        try:
            for ln in latest.read_text().splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                t = str(r.get("ticker") or "").upper()
                if t:
                    surf[t] = r
        except Exception:
            pass
        return surf, day

    def _read_panel(self):
        out = []
        try:
            for ln in self.OUT.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            return []
        return out

    # -------------------------------------------------------- record side

    def record_implied(self, save=True):
        """Snapshot what the options market is CHARGING for each upcoming earnings move.

        This is the half that cannot be reconstructed later. Recorded once per (ticker, event).
        """
        upcoming = self._upcoming_earnings()
        surf, surf_day = self._latest_surface()
        if not surf:
            return {"status": "NO_OPTIONS_SURFACE", "recorded": 0,
                    "detail": "capture the options surface first — implied move is unrecoverable later"}

        existing = {(r.get("ticker"), r.get("report_date")) for r in self._read_panel()
                    if r.get("kind") == "implied"}
        rows = []
        for t, rdate in upcoming.items():
            if (t, rdate) in existing:
                continue
            s = surf.get(t.upper())
            if not s:
                continue
            im = self._f(s.get("implied_move_perc"))
            if im is None:
                im = self._f(s.get("implied_move"))
                close = self._f(s.get("close"))
                im = (im / close * 100.0) if (im and close) else None
            else:
                im = im * 100.0 if im < 1.5 else im     # normalise fraction -> percent
            if im is None or im <= self.MIN_IMPLIED_PCT:
                continue
            rows.append({
                "kind": "implied", "ticker": t, "report_date": rdate,
                "captured_on": surf_day,
                "implied_move_pct": round(im, 3),
                "iv30d": self._f(s.get("iv30d")),
                "iv_rank": self._f(s.get("iv_rank")),
                "realized_vol": self._f(s.get("realized_volatility")),
                "variance_risk_premium": self._f(s.get("variance_risk_premium")),
                "recorded_at": datetime.utcnow().isoformat(),
            })

        if save and rows:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                with open(self.OUT, "a") as f:
                    for r in rows:
                        f.write(json.dumps(r) + "\n")
            except Exception as e:
                return {"status": "PANEL_WRITE_FAILED", "error": str(e)[:120]}

        return {"status": "IMPLIED_RECORDED", "recorded": len(rows),
                "upcoming_events": len(upcoming), "surface_day": surf_day}

    def resolve_realized(self, save=True):
        """After each announcement, measure what the move ACTUALLY was, and pair it."""
        panel = self._read_panel()
        implied = [r for r in panel if r.get("kind") == "implied"]
        done = {(r.get("ticker"), r.get("report_date")) for r in panel if r.get("kind") == "resolved"}
        if not implied:
            return {"status": "NOTHING_TO_RESOLVE", "resolved": 0}

        rows = []
        for r in implied:
            key = (r.get("ticker"), r.get("report_date"))
            if key in done:
                continue
            closes = {}
            p = self.PRICE_DIR / f"{r['ticker']}_total_return.csv"
            if not p.exists():
                continue
            try:
                with open(p) as f:
                    for x in csv.DictReader(f):
                        try:
                            closes[str(x["date"])[:10]] = float(x["adj_close"])
                        except Exception:
                            continue
            except Exception:
                continue
            ds = sorted(closes)
            rd = r["report_date"]
            after = [d for d in ds if d > rd]
            before = [d for d in ds if d < rd]
            if len(after) < 2 or not before:
                continue                      # event hasn't fully resolved yet
            a, b = closes[before[-1]], closes[after[1]]
            if not a or a <= 0:
                continue
            realized = abs(b / a - 1.0) * 100.0
            im = r.get("implied_move_pct")
            rows.append({
                "kind": "resolved", "ticker": r["ticker"], "report_date": rd,
                "implied_move_pct": im, "realized_move_pct": round(realized, 3),
                "spread_pct": round((im - realized), 3) if im is not None else None,
                "iv_rank": r.get("iv_rank"),
                "variance_risk_premium": r.get("variance_risk_premium"),
                "resolved_at": datetime.utcnow().isoformat(),
            })

        if save and rows:
            try:
                with open(self.OUT, "a") as f:
                    for x in rows:
                        f.write(json.dumps(x) + "\n")
            except Exception as e:
                return {"status": "PANEL_WRITE_FAILED", "error": str(e)[:120]}
        return {"status": "REALIZED_RESOLVED", "resolved": len(rows)}

    # ------------------------------------------------------------ verdict

    def panel_status(self):
        """What the accumulating experiment shows — with NO verdict until it is powered."""
        panel = self._read_panel()
        implied = [r for r in panel if r.get("kind") == "implied"]
        resolved = [r for r in panel if r.get("kind") == "resolved" and r.get("spread_pct") is not None]
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "implied_recorded": len(implied),
            "events_resolved": len(resolved),
            "verdict": "INSUFFICIENT_DATA",
            "note": ("Implied move cannot be reconstructed historically (no options history "
                     "exists), so this experiment only accrues FORWARD. No verdict is offered "
                     "until the sample is powered."),
        }
        if len(resolved) >= 200:
            spreads = [r["spread_pct"] for r in resolved]
            mean = sum(spreads) / len(spreads)
            overpriced = sum(1 for s in spreads if s > 0) / len(spreads)
            out.update({
                "mean_spread_implied_minus_realized_pct": round(mean, 3),
                "pct_events_options_overpriced": round(overpriced, 3),
                "verdict": "PANEL_ACCUMULATING_REVIEW_READY",
                "reading": ("positive spread = options overprice earnings moves (selling "
                            "premium is favoured); negative = they underprice (buying is)"),
            })
        return out
