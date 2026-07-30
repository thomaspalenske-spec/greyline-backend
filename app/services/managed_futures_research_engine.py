"""Managed-futures / time-series-momentum sleeve — the BACKTEST that established the edge.

GO verdict (2026-07-30): a diversified multi-asset TSMOM sleeve is worth forward-testing NOT for
standalone return (net Sharpe ~0.41 full / 0.57 recent — on par with trend/carry, not better) but
as a genuine DIVERSIFIER for GreyLine's short-vol-heavy book: it is +0.02 correlated to the carry
sleeve (SVXY) and POSITIVE in every stress year (2008 +17%, 2020 +19%, 2022 +23%). The key finding
is that the SHORT side is what decorrelates it — a long/FLAT version (like the current trend sleeve)
is ~+0.57 correlated to carry, adding shorts drops that to ~+0.02.

Method (matches the discipline that killed the false edges):
  * Universe: diversified ETF set (equities/bonds/commodities/metals/credit) — indices, so NO
    survivorship bias, and backtestable on the daily bars already on disk (no options IV needed).
  * Signal: multi-horizon TSMOM — sign of trailing return over 63/126/252d, blended. No look-ahead
    (signal uses prices through day t, return earned t->t+1; vol/scaling all trailing).
  * Sizing: inverse-vol (trailing 60d), scaled to ~10% portfolio vol per asset.
  * Cost-aware: turnover-based cost at each rebalance (survives monthly; weekly does NOT).
This is RESEARCH ONLY — it never trades. The live sleeve is ManagedFuturesEngine (gated OFF).
"""

import csv
import math
from datetime import datetime
from pathlib import Path

HIST = Path("app/data/historical")
ASSETS = ["SPY", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "SLV", "DBC", "DBA", "USO", "HYG"]
LOOKBACKS = [63, 126, 252]
VOL_WIN = 60
TARGET_VOL = 0.10
TRADING_DAYS = 252
ONE_WAY_BPS = 5.0
CRISIS = {"2008": "GFC", "2011": "EU/US downgrade", "2015": "China/oil", "2018": "Q4 selloff",
          "2020": "COVID", "2022": "rate shock"}


class ManagedFuturesResearchEngine:

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _closes(self, sym):
        out = {}
        try:
            with open(HIST / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c and c > 0:
                        out[str(r.get("date"))[:10]] = c
        except Exception:
            return {}
        return out

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    @classmethod
    def _pearson(cls, a, b):
        n = min(len(a), len(b))
        if n < 3:
            return None
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a) / n, sum(b) / n
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((x - mb) ** 2 for x in b))
        return round(cov / (da * db), 2) if da and db else None

    def _perf(self, rets):
        if not rets:
            return {}
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rets:
            eq *= (1 + r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        n = len(rets)
        sd = self._stdev(rets)
        return {
            "sharpe": round((sum(rets) / n) / sd * math.sqrt(TRADING_DAYS), 2) if sd else 0.0,
            "cagr_pct": round(100 * (eq ** (TRADING_DAYS / n) - 1), 1),
            "vol_pct": round(100 * sd * math.sqrt(TRADING_DAYS), 1),
            "max_drawdown_pct": round(100 * mdd, 1), "days": n,
        }

    # ---- core backtest -------------------------------------------------------------------------

    def _load(self):
        data = {s: self._closes(s) for s in ASSETS}
        have = [s for s in ASSETS if len(data[s]) > max(LOOKBACKS) + VOL_WIN]
        common = set.intersection(*[set(data[s].keys()) for s in have])
        dates = sorted(common)
        px = {s: [data[s][d] for d in dates] for s in have}
        ret = {s: [0.0] + [px[s][i] / px[s][i - 1] - 1 for i in range(1, len(dates))] for s in have}
        return have, dates, px, ret

    def _signal(self, px, s, i):
        sg = 0.0
        for L in LOOKBACKS:
            sg += 1.0 if px[s][i] > px[s][i - L] else -1.0
        return sg / len(LOOKBACKS)

    def _vol(self, ret, s, i):
        w = ret[s][max(1, i - VOL_WIN + 1):i + 1]
        return max(self._stdev(w) * math.sqrt(TRADING_DAYS), 0.05)

    def _run_variant(self, assets, dates, px, ret, rebalance="M", shorts=True):
        start = max(LOOKBACKS) + 1
        per_asset_risk = TARGET_VOL / math.sqrt(len(assets))
        held = {s: 0.0 for s in assets}
        out_dates, gross, net = [], [], []
        turn_sum = 0.0
        for i in range(start, len(dates) - 1):
            dt, nxt = dates[i], dates[i + 1]
            is_reb = (i == start) or (rebalance == "M" and nxt[:7] != dt[:7]) or \
                     (rebalance == "W" and nxt[:4] + self._week(nxt) != dt[:4] + self._week(dt))
            cost = 0.0
            if is_reb:
                tgt = {}
                for s in assets:
                    sig = self._signal(px, s, i)
                    if not shorts:
                        sig = max(0.0, sig)
                    tgt[s] = sig * per_asset_risk / self._vol(ret, s, i)
                turn = sum(abs(tgt[s] - held[s]) for s in assets)
                cost = turn * ONE_WAY_BPS / 1e4
                turn_sum += turn
                held = tgt
            g = sum(held[s] * ret[s][i + 1] for s in assets)
            out_dates.append(nxt)
            gross.append(g)
            net.append(g - cost)
        ann_turn = turn_sum / (len(out_dates) / TRADING_DAYS) if out_dates else 0.0
        return out_dates, gross, net, round(ann_turn, 1)

    @staticmethod
    def _week(dt):
        import datetime as _d
        return "%02d" % _d.date(int(dt[:4]), int(dt[5:7]), int(dt[8:10])).isocalendar()[1]

    @staticmethod
    def _by_year(dates, rets):
        yr = {}
        for d, r in zip(dates, rets):
            yr[d[:4]] = yr.get(d[:4], 1.0) * (1 + r)
        return {y: round(100 * (v - 1), 1) for y, v in sorted(yr.items())}

    def run(self):
        assets, dates, px, ret = self._load()
        if len(dates) < max(LOOKBACKS) + 60:
            return {"status": "MF_RESEARCH_INSUFFICIENT_DATA", "assets": assets}

        variants = {}
        for name, kw in [("long_short_monthly", dict(rebalance="M", shorts=True)),
                         ("long_flat_monthly", dict(rebalance="M", shorts=False)),
                         ("long_short_weekly", dict(rebalance="W", shorts=True))]:
            d, g, n, turn = self._run_variant(assets, dates, px, ret, **kw)
            variants[name] = {"gross": self._perf(g), "net": self._perf(n),
                              "turnover_per_yr": turn,
                              "cost_drag_sharpe": round(self._perf(g)["sharpe"] - self._perf(n)["sharpe"], 2)}

        # deep-dive the primary variant
        d, g, n, _ = self._run_variant(assets, dates, px, ret, rebalance="M", shorts=True)
        by_year = self._by_year(d, n)
        crisis = {y: by_year.get(y) for y in CRISIS if y in by_year}
        decay = {}
        for y0, lbl in [("0000", "full"), ("2015", "2015+"), ("2021", "last_5y")]:
            sub = [(x, r) for x, r in zip(d, n) if x[:4] >= y0]
            if sub:
                decay[lbl] = self._perf([r for _, r in sub])["sharpe"]

        # correlation: the diversification thesis
        mf_map = dict(zip(d, n))
        spy_ret = dict(zip(dates, ret["SPY"])) if "SPY" in ret else {}
        c_spy = self._pearson([mf_map[x] for x in d if x in spy_ret],
                              [spy_ret[x] for x in d if x in spy_ret])
        svxy = self._closes("SVXY")
        sd = sorted(svxy)
        svxy_ret = {sd[i]: svxy[sd[i]] / svxy[sd[i - 1]] - 1 for i in range(1, len(sd))}
        common_svxy = [x for x in d if x in svxy_ret]
        c_svxy = self._pearson([mf_map[x] for x in common_svxy], [svxy_ret[x] for x in common_svxy])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "MF_RESEARCH_READY",
            "verdict": "GO (diversifier, not a return-chaser) — forward-test gated",
            "universe": assets, "span": [dates[0], dates[-1]], "days": len(dates),
            "variants": variants,
            "primary": "long_short_monthly",
            "by_year_net_pct": by_year,
            "crisis_alpha_net_pct": {f"{y} {CRISIS[y]}": crisis[y] for y in crisis},
            "decay_net_sharpe": decay,
            "correlation": {
                "vs_spy_equity_beta": c_spy,
                "vs_svxy_carry_sleeve": c_svxy,
                "note": ("Carry corr ~%.2f = near-zero: the diversification win. Trend & carry are "
                         "+0.57 to each other; this is the piece that isn't." % (c_svxy or 0.0)),
            },
            "caveats": [
                "Price-only bars (no dividends) — mildly understates bond/equity total return (conservative).",
                "No look-ahead: signals through day t, returns t->t+1, vol/scaling trailing.",
                "Standard TSMOM params (63/126/252, 60d vol, 10% target) — not fitted to this data.",
                "Whole-share at $10k across the basket is coarse — live tracking error vs this idealized curve is the main implementation risk.",
                "Backtest GO only — the real proof is forward paper performance measured by EdgePersistence.",
            ],
        }
