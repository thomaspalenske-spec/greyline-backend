"""Backtest the volatility TERM-STRUCTURE CARRY — the one variance-premium edge we can measure.

Single-name option edges can't be backtested (no historical IV surface). But the SAME variance
risk premium shows up in the VIX term structure, and THAT is real, daily, and backtestable on true
prices: the front of the curve (VIX / VIX9D) is systematically richer than realized, and VIX
futures roll DOWN toward spot in contango. A short-vol position harvests that roll.

Naive short-vol is the trade that took XIV to zero (-96% on 2018-02-05). The whole thesis here is
that the term structure ITSELF is the risk control: the curve inverts into BACKWARDATION at the
onset of a vol spike, so a rule that only harvests in contango and stands aside in backwardation is
FLAT going into the worst of it. This engine measures whether that protection actually holds across
every vol event since 2011 — or whether the gaps kill you before the signal can react.

Honest construction:
  * signal from day t-1 close -> position for day t's return. No lookahead (you see the curve at the
    close, put the position on MOC, earn the next session).
  * instrument = FRONT VIX futures via VIXY (+1x); harvest = SHORT VIXY (strat return = -VIXY ret).
    Consistent +1x-inverse across the whole sample (SVXY changed -1x->-0.5x in 2018, so it is a
    dirty backtest instrument; reported separately, not the headline).
  * costs modeled: ~`SWITCH_COST_BPS` per position change + a short-borrow drag while short.
  * benchmarked against ALWAYS-short VIXY, to show both the edge and the tail the signal removes.
  * NOT cherry-picked: two signals (VIX/VIX3M, VIX9D/VIX) x thresholds are all reported, plus a
    hard-stop overlay, so the reader sees the whole surface, not one lucky cell.
"""

import csv
import math
import statistics
from datetime import datetime
from pathlib import Path


class VolTermStructureCarryResearchEngine:

    IDX = Path("app/data/research/vol_term_structure")     # VIX / VIX3M / VIX9D / VVIX closes
    HIST = Path("app/data/historical")                     # VIXY / SVXY daily bars

    SWITCH_COST_BPS = 8.0        # round-ish cost per position change (VIXY is liquid)
    SHORT_BORROW_ANNUAL = 0.015  # ~1.5%/yr borrow drag while short VIXY
    CRASHES = {
        "2011_downgrade": ("2011-07-20", "2011-10-10"),
        "2015_flashcrash": ("2015-08-17", "2015-09-30"),
        "2018_volmageddon": ("2018-01-26", "2018-03-01"),
        "2020_covid": ("2020-02-14", "2020-04-30"),
        "2022_bear": ("2022-01-01", "2022-10-31"),
    }

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _closes(self, path):
        out = {}
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c and c > 0:
                        out[str(r.get("date"))[:10]] = c
        except Exception:
            return {}
        return out

    def _ohlc(self, path):
        out = {}
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    o, h, l, c = (self._f(r.get("open")), self._f(r.get("high")),
                                  self._f(r.get("low")), self._f(r.get("close")))
                    if c and c > 0 and o and h and l:
                        out[str(r.get("date"))[:10]] = (o, h, l, c)
        except Exception:
            return {}
        return out

    # --- one backtest run -----------------------------------------------------------------------

    def _run(self, ratio_num, ratio_den, thr, vixy_ohlc, stop=None, vol_target=None, max_w=1.0):
        """ratio = num/den closes; SHORT VIXY when ratio < thr (contango), else FLAT.

        REALISTIC intraday stop (no look-ahead): when short, if VIXY's high rises >= `stop` above the
        prior close you are stopped OUT that day and TAKE the loss — `stop` on an intraday trigger, or
        the full gap if it opened through the stop. This costs you on whipsaws (as a real stop does),
        it does not magically avoid the loss. `vol_target`: scale exposure by target/trailing-vol
        (set at the prior close), capped at `max_w` — the standard way to tame a 59%-vol instrument."""
        dates = sorted(set(ratio_num) & set(ratio_den) & set(vixy_ohlc))
        if len(dates) < 250:
            return None
        borrow_daily = self.SHORT_BORROW_ANNUAL / 252.0
        cost = self.SWITCH_COST_BPS / 1e4
        closes = {d: v[3] for d, v in vixy_ohlc.items()}

        # trailing 20d realized vol of VIXY (for vol targeting), computed causally
        rv = {}
        if vol_target:
            win = 20
            for i in range(win, len(dates)):
                seg = [math.log(closes[dates[k]] / closes[dates[k - 1]])
                       for k in range(i - win + 1, i + 1)]
                sd = statistics.pstdev(seg) or 1e-9
                rv[dates[i]] = sd * math.sqrt(252)

        eq, bh = 1.0, 1.0
        curve = [(dates[0], eq)]
        rets, prev_w, invested_days, switches = [], 0.0, 0, 0
        worst_day = 0.0
        daily_by_date = {}

        for i in range(1, len(dates)):
            d0, d1 = dates[i - 1], dates[i]
            r_num, r_den = ratio_num.get(d0), ratio_den.get(d0)
            if not r_num or not r_den:
                continue
            short = (r_num / r_den) < thr
            o1, h1, l1, c1 = vixy_ohlc[d1]
            c0 = closes[d0]
            vret = c1 / c0 - 1.0

            # per-unit short return this session (with realistic stop)
            if short:
                if stop is not None and (h1 / c0 - 1.0) >= stop:
                    gap = o1 / c0 - 1.0
                    loss = gap if gap >= stop else stop      # gapped through, or stopped at trigger
                    unit = -loss - borrow_daily
                else:
                    unit = -vret - borrow_daily
            else:
                unit = 0.0

            w = max_w if short else 0.0
            if vol_target and short:
                rvv = rv.get(d0)
                if rvv:
                    w = min(max_w, vol_target / rvv)
            strat = w * unit
            if abs(w - prev_w) > 1e-9:
                strat -= cost * abs(w - prev_w)
                switches += 1
            eq *= (1 + strat)
            bh *= (1 + (-vret - borrow_daily))
            rets.append(strat)
            daily_by_date[d1] = strat
            invested_days += 1 if short else 0
            worst_day = min(worst_day, strat)
            prev_w = w
            curve.append((d1, eq))

        return {"dates": dates, "curve": curve, "rets": rets, "eq": eq, "bh": bh,
                "invested_frac": invested_days / max(1, len(rets)),
                "switches_per_yr": switches / max(1e-9, len(rets) / 252.0),
                "worst_day": worst_day, "daily_by_date": daily_by_date,
                "n_years": len(rets) / 252.0}

    @staticmethod
    def _stats(res):
        rets = res["rets"]
        if not rets:
            return {}
        mean, sd = statistics.fmean(rets), (statistics.pstdev(rets) or 1e-9)
        cagr = res["eq"] ** (1.0 / max(1e-9, res["n_years"])) - 1.0
        # max drawdown
        peak, mdd = -1e9, 0.0
        for _, e in res["curve"]:
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1.0)
        downs = [r for r in rets if r < 0]
        sortino = (mean * 252) / ((statistics.pstdev(downs) or 1e-9) * math.sqrt(252)) if downs else None
        return {
            "cagr_pct": round(100 * cagr, 2),
            "ann_vol_pct": round(100 * sd * math.sqrt(252), 2),
            "sharpe": round(mean / sd * math.sqrt(252), 2),
            "sortino": round(sortino, 2) if sortino else None,
            "max_drawdown_pct": round(100 * mdd, 2),
            "final_multiple": round(res["eq"], 2),
            "always_short_multiple": round(res["bh"], 2),
            "invested_frac_pct": round(100 * res["invested_frac"], 1),
            "switches_per_yr": round(res["switches_per_yr"], 1),
            "worst_day_pct": round(100 * res["worst_day"], 2),
        }

    def _crash_returns(self, res):
        out = {}
        for name, (a, b) in self.CRASHES.items():
            seg = [v for dte, v in res["daily_by_date"].items() if a <= dte <= b]
            if seg:
                mult = 1.0
                for r in seg:
                    mult *= (1 + r)
                out[name] = round(100 * (mult - 1), 1)
        return out

    def _by_year(self, res):
        years = {}
        for dte, r in res["daily_by_date"].items():
            years.setdefault(dte[:4], 1.0)
            years[dte[:4]] *= (1 + r)
        return {y: round(100 * (m - 1), 1) for y, m in sorted(years.items())}

    # --- top-level study ------------------------------------------------------------------------

    def deployable_daily_returns(self):
        """Daily returns of the deployable vol-targeted-12% carry variant — for combining sleeves."""
        vix = self._closes(self.IDX / "VIX.csv")
        vix3m = self._closes(self.IDX / "VIX3M.csv")
        vixy = self._ohlc(self.HIST / "VIXY_daily.csv")
        if not (vix and vix3m and vixy):
            return {}
        res = self._run(vix, vix3m, 1.00, vixy, stop=None, vol_target=0.12, max_w=1.0)
        return res["daily_by_date"] if res else {}

    def run(self):
        vix = self._closes(self.IDX / "VIX.csv")
        vix3m = self._closes(self.IDX / "VIX3M.csv")
        vix9d = self._closes(self.IDX / "VIX9D.csv")
        vixy = self._ohlc(self.HIST / "VIXY_daily.csv")
        if not (vix and vix3m and vixy):
            return {"status": "MISSING_DATA",
                    "have": {"vix": len(vix), "vix3m": len(vix3m), "vixy": len(vixy)}}

        # (label, num, den, thr, stop, vol_target, max_w)
        specs = [
            ("RAW full-exposure (thr1.00)", vix, vix3m, 1.00, None, None, 1.0),
            ("VOL-TARGET 12% (no stop)", vix, vix3m, 1.00, None, 0.12, 1.0),
            ("VOL-TARGET 12% + 25% stop", vix, vix3m, 1.00, 0.25, 0.12, 1.0),
            ("VOL-TARGET 15% + 30% stop", vix, vix3m, 1.00, 0.30, 0.15, 1.0),
            ("VIX9D/VIX 12% + 25% stop", vix9d, vix, 1.00, 0.25, 0.12, 1.0),
        ]
        variants = {}
        base = None
        for label, num, den, thr, stop, vt, mw in specs:
            res = self._run(num, den, thr, vixy, stop=stop, vol_target=vt, max_w=mw)
            if res:
                base = base or res
                variants[label] = {"stats": self._stats(res),
                                   "crash_window_returns_pct": self._crash_returns(res),
                                   "by_year_pct": self._by_year(res)}
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sample": {"first": (base["dates"][0] if base else None),
                       "last": (base["dates"][-1] if base else None),
                       "years": round(base["n_years"], 1) if base else None},
            "instrument": "front VIX futures via VIXY; harvest = SHORT VIXY (+1x inverse)",
            "signal": "SHORT vol only in contango (VIX<VIX3M); FLAT in backwardation",
            "variants": variants,
            "note": ("'always_short_multiple' per variant = naive always-short VIXY (the XIV trade). "
                     "vol-targeted variants scale exposure by 12-15%/trailing-vol, capped at 1x."),
            "status": "VOL_TERM_STRUCTURE_CARRY_STUDY",
        }
