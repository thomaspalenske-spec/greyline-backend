"""Backtest TIME-SERIES MOMENTUM (trend-following) — the long-convexity complement to short-vol.

GreyLine's real edges (VRP, earnings crush, vol term-structure carry) are ALL short-volatility: they
bleed premium in calm and lose in crashes. A book made only of those is one violent spike from giving
everything back. The structurally-correct fix is a sleeve that is POSITIVE-expectancy on its own AND
profits when the short-vol sleeves bleed. Trend-following is that sleeve: it holds an asset only while
its own price trend is up and steps to cash when the trend breaks, so it sidesteps the big drawdowns
(2008, 2020, 2022) that define equity risk. That is 'minimize losses' as a mechanism, not a slogan.

NOT the cross-sectional single-stock momentum GreyLine proved null — this is each asset vs ITS OWN
trend (Moskowitz-Ooi-Pedersen time-series momentum), on a diversified ETF basket, backtestable on
real TS price bars.

Honest construction:
  * signal from close t (price vs its own SMA) -> position for t+1. No lookahead.
  * long/FLAT only (no shorting): in an uptrend hold the ETF; else sit in cash earning ~RF. Defined,
    simple, and the cash step is the crash protection.
  * costs modeled per position change (trend flips a few times/yr — trivial turnover).
  * CAVEAT stated, not hidden: bars are PRICE-ONLY (no dividends). Both trend and buy-and-hold miss
    the dividend while invested (~wash on the comparison); trend earns RF while in cash. Trend also
    STRUCTURALLY underperforms buy-and-hold in a low-vol melt-up with V-shaped recoveries (2010s) —
    the per-year table shows it. The edge is risk-adjusted (Sharpe / drawdown), not raw CAGR.
"""

import csv
import math
import statistics
from datetime import datetime
from pathlib import Path


class TrendFollowingResearchEngine:

    HIST = Path("app/data/historical")
    BASKET = ["SPY", "QQQ", "IWM", "TLT", "GLD", "EFA", "DBC"]   # equities, bonds, gold, intl, cmdty
    SMA = 200                 # classic long-term trend filter
    RF_ANNUAL = 0.02          # cash yield when flat (a conservative constant; rates varied 0-5%)
    SWITCH_COST_BPS = 5.0
    CRASHES = {
        "2008_gfc": ("2008-01-01", "2009-03-31"),
        "2020_covid": ("2020-02-14", "2020-04-30"),
        "2022_bear": ("2022-01-01", "2022-10-31"),
    }

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _closes(self, sym):
        out = {}
        try:
            with open(self.HIST / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c and c > 0:
                        out[str(r.get("date"))[:10]] = c
        except Exception:
            return {}
        return out

    def _trend_series(self, sym):
        """{date: strategy daily return} for long/flat SMA trend on one asset, + buy-and-hold."""
        closes = self._closes(sym)
        if len(closes) < self.SMA + 10:
            return None
        ds = sorted(closes)
        rf_daily = self.RF_ANNUAL / 252.0
        cost = self.SWITCH_COST_BPS / 1e4
        strat, bh, prev_pos, switches, invested = {}, {}, 0, 0, 0
        for i in range(self.SMA - 1, len(ds) - 1):
            window = ds[i - self.SMA + 1:i + 1]
            sma = sum(closes[d] for d in window) / self.SMA
            pos = 1 if closes[ds[i]] > sma else 0
            ret = closes[ds[i + 1]] / closes[ds[i]] - 1.0
            s = (pos * ret) + ((1 - pos) * rf_daily)
            if pos != prev_pos:
                s -= cost
                switches += 1
            strat[ds[i + 1]] = s
            bh[ds[i + 1]] = ret
            invested += pos
            prev_pos = pos
        n = max(1, len(strat))
        return {"strat": strat, "bh": bh, "invested_frac": invested / n,
                "switches_per_yr": switches / max(1e-9, n / 252.0), "n": n}

    @staticmethod
    def _stats(daily):
        rets = list(daily.values())
        if not rets:
            return {}
        mean, sd = statistics.fmean(rets), (statistics.pstdev(rets) or 1e-9)
        eq, curve = 1.0, []
        for d in sorted(daily):
            eq *= (1 + daily[d])
            curve.append(eq)
        peak, mdd = -1e9, 0.0
        for e in curve:
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1.0)
        yrs = len(rets) / 252.0
        cagr = eq ** (1.0 / max(1e-9, yrs)) - 1.0
        return {"cagr_pct": round(100 * cagr, 2), "ann_vol_pct": round(100 * sd * math.sqrt(252), 2),
                "sharpe": round(mean / sd * math.sqrt(252), 2),
                "max_drawdown_pct": round(100 * mdd, 2), "final_multiple": round(eq, 2)}

    def _crash(self, daily):
        out = {}
        for name, (a, b) in self.CRASHES.items():
            seg = [v for d, v in daily.items() if a <= d <= b]
            if seg:
                m = 1.0
                for r in seg:
                    m *= (1 + r)
                out[name] = round(100 * (m - 1), 1)
        return out

    @staticmethod
    def _by_year(daily):
        years = {}
        for d, r in daily.items():
            years.setdefault(d[:4], 1.0)
            years[d[:4]] *= (1 + r)
        return {y: round(100 * (m - 1), 1) for y, m in sorted(years.items())}

    def run(self):
        per_asset, basket_strat = {}, {}
        counts = {}
        for sym in self.BASKET:
            ts = self._trend_series(sym)
            if not ts:
                continue
            per_asset[sym] = {"trend": self._stats(ts["strat"]), "buy_hold": self._stats(ts["bh"]),
                              "invested_frac_pct": round(100 * ts["invested_frac"], 1),
                              "switches_per_yr": round(ts["switches_per_yr"], 1),
                              "crash_pct": self._crash(ts["strat"]),
                              "buy_hold_crash_pct": self._crash(ts["bh"])}
            for d, v in ts["strat"].items():                 # equal-weight basket = mean across assets
                basket_strat.setdefault(d, [])
                basket_strat[d].append(v)
        basket = {d: statistics.fmean(v) for d, v in basket_strat.items()}
        spy_bh = self._trend_series("SPY")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "config": {"basket": self.BASKET, "sma": self.SMA, "long_flat": True,
                       "rf_annual_pct": 100 * self.RF_ANNUAL},
            "per_asset": per_asset,
            "equal_weight_trend_basket": {
                "stats": self._stats(basket), "crash_pct": self._crash(basket),
                "by_year_pct": self._by_year(basket),
                "sample": {"first": min(basket) if basket else None,
                           "last": max(basket) if basket else None}},
            "spy_buy_hold_benchmark": self._stats(spy_bh["bh"]) if spy_bh else {},
            "spy_buy_hold_crash_pct": self._crash(spy_bh["bh"]) if spy_bh else {},
            "status": "TREND_FOLLOWING_STUDY",
        }

    def basket_daily_returns(self):
        """The equal-weight trend basket's daily return series — for combining with the carry sleeve."""
        acc = {}
        for sym in self.BASKET:
            ts = self._trend_series(sym)
            if ts:
                for d, v in ts["strat"].items():
                    acc.setdefault(d, []).append(v)
        return {d: statistics.fmean(v) for d, v in acc.items()}
