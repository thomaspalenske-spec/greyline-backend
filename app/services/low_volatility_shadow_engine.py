"""Low-volatility (BAB) EQUITY SHADOW forward-test — measures the sleeve's edge with ZERO capital.

The low-vol sleeve is parked (GREYLINE_LOW_VOL_ENABLED off) pending a clean single-sleeve edge test. Like
the momentum-equity shadow, it's an EQUITY strategy so it CAN be measured honestly on settled bars: hold
the sleeve's real inverse-vol basket and mark a hypothetical daily P&L, NO orders, NO budget — so the
edge accrues while the sleeve is off and we learn if it earns its way back on before committing capital.

Method mirrors ManagedFuturesShadowEngine (settled-bar daily marking, monthly rebalance) but uses the
LIVE LowVolatilityEngine's OWN inverse-vol weights (USMV/SPLV/EFAV/XMLV, 60d realized-vol, weights sum to
1, fully invested long-only) — no reimplementation of the weighting, so the shadow == the sleeve. The
low-vol THESIS is smaller drawdown than the broad market, so the report compares max drawdown to SPY over
the same shadow dates (the thesis check, analogous to the MF shadow's carry-corr). Accumulates FORWARD
from first run (no backfill), driven by settled bars, self-gated once per new bar.
"""

import csv
import math
from datetime import datetime
from os import getenv
from pathlib import Path


class LowVolatilityShadowEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/low_volatility")
    LEDGER = STATE / "shadow_ledger.jsonl"
    BENCHMARK = "SPY"             # the low-vol thesis: draw down LESS than the broad market
    VOL_WIN = 60
    TRADING_DAYS = 252
    MIN_DAYS = 10                 # accumulating until this many marked days (mirrors the other shadows)

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def enabled():
        # default TRUE — accumulate live evidence while the sleeve is parked; it NEVER places an order.
        return (getenv("GREYLINE_LOW_VOL_SHADOW", "true") or "true").strip().lower() == "true"

    @property
    def _basket(self):
        try:
            from app.services.low_volatility_engine import LowVolatilityEngine
            return list(LowVolatilityEngine.BASKET)
        except Exception:
            return ["USMV", "SPLV", "EFAV", "XMLV"]

    def _live_weights(self):
        """The sleeve's OWN current inverse-vol weights (sum to 1). {} if the engine can't weight (stale)."""
        try:
            from app.services.low_volatility_engine import LowVolatilityEngine
            w, _vols = LowVolatilityEngine()._weights()
            return w or {}
        except Exception:
            return {}

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

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    def _aligned(self):
        basket = self._basket
        data = {s: self._closes(s) for s in basket}
        have = [s for s in basket if len(data[s]) > self.VOL_WIN + 2]
        if not have:
            return [], [], {}
        common = sorted(set.intersection(*[set(data[s]) for s in have]))
        px = {s: [data[s][d] for d in common] for s in have}
        return have, common, px

    def _rebalance_weights(self, have):
        """Prefer the LIVE sleeve's inverse-vol weights (restricted to names we have bars for, renormalized);
        equal-weight fallback so a stale vol read never stops the forward-test."""
        w = {s: v for s, v in self._live_weights().items() if s in have and v and v > 0}
        tot = sum(w.values())
        if tot > 0:
            return {s: w[s] / tot for s in w}
        return {s: 1.0 / len(have) for s in have}     # equal-weight fallback (fully invested)

    def _last_entry(self):
        import json
        try:
            for ln in reversed(self.LEDGER.read_text().splitlines()):
                if ln.strip():
                    return json.loads(ln)
        except Exception:
            pass
        return None

    def mark(self):
        """Advance one settled bar: book yesterday's weights' P&L, then (monthly) rebalance."""
        import json
        if not self.enabled():
            return {"status": "LOWVOL_SHADOW_DISABLED", "acted": False}
        have, common, px = self._aligned()
        if len(common) < self.VOL_WIN + 2:
            return {"status": "LOWVOL_SHADOW_INSUFFICIENT_DATA", "acted": False}
        i = len(common) - 1
        latest = common[i]
        last = self._last_entry()
        if last and str(last.get("date") or "") >= latest:
            return {"status": "LOWVOL_SHADOW_NO_NEW_BAR", "acted": False, "date": latest}

        closes_now = {s: px[s][i] for s in have}
        daily_return = None
        if last and last.get("closes") and last.get("weights"):
            dr = 0.0
            for s in have:
                pc = last["closes"].get(s)
                if pc:
                    dr += last["weights"].get(s, 0.0) * (closes_now[s] / pc - 1)
            daily_return = round(dr, 6)

        month = latest[:7]
        rebalanced = not (last and last.get("month") == month and last.get("weights"))
        weights = self._rebalance_weights(have) if rebalanced else last["weights"]

        entry = {"date": latest, "month": month, "weights": weights,
                 "closes": {s: round(closes_now[s], 4) for s in have},
                 "daily_return": daily_return, "rebalanced": rebalanced,
                 "marked_at": datetime.utcnow().isoformat()}
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            return {"status": "LOWVOL_SHADOW_WRITE_FAILED", "acted": False, "error": repr(e)}
        return {"status": "LOWVOL_SHADOW_MARKED", "acted": True, "date": latest,
                "daily_return": daily_return, "rebalanced": rebalanced}

    # ---- report --------------------------------------------------------------------------------

    def _entries(self):
        import json
        out = []
        try:
            for ln in self.LEDGER.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    @staticmethod
    def _curve_stats(rets):
        """(cumulative_return, annualized_sharpe, max_drawdown) for a daily-return series."""
        if not rets:
            return 0.0, 0.0, 0.0
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rets:
            eq *= (1 + r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        sd = LowVolatilityShadowEngine._stdev(rets)
        sharpe = round((sum(rets) / len(rets)) / sd * math.sqrt(252), 2) if sd else 0.0
        return round(eq - 1, 6), sharpe, round(mdd, 6)

    def report(self):
        entries = self._entries()
        rr = [(e["date"], e["daily_return"]) for e in entries if e.get("daily_return") is not None]
        days = len(rr)
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "LowVolatilityShadowEngine",
            "basket": self._basket, "weighting": "inverse_volatility",
            "days_tracked": days, "min_days": self.MIN_DAYS,
            "since": rr[0][0] if rr else None, "through": rr[-1][0] if rr else None,
            "note": ("SHADOW forward-test of the low-vol (BAB) inverse-vol ETF basket — hypothetical daily "
                     "P&L on settled bars, NO orders, NO budget. Thesis check = smaller drawdown than SPY."),
        }
        if days == 0:
            return {**base, "status": "LOWVOL_SHADOW_NO_DATA",
                    "verdict": "no marks yet — starts on the next settled bar"}

        rets = [r for _, r in rr]
        cum, sharpe, mdd = self._curve_stats(rets)

        # SPY benchmark over the SAME shadow dates — the thesis is a SMALLER drawdown than the market.
        spy = self._closes(self.BENCHMARK)
        sdates = sorted(spy)
        spy_ret = {sdates[k]: spy[sdates[k]] / spy[sdates[k - 1]] - 1 for k in range(1, len(sdates))}
        bench = [spy_ret[d] for d, _ in rr if d in spy_ret]
        b_cum, b_sharpe, b_mdd = self._curve_stats(bench) if len(bench) >= 2 else (None, None, None)
        dd_ratio = round(mdd / b_mdd, 2) if (b_mdd and b_mdd < 0) else None   # <1 == less drawdown (thesis holds)

        accumulating = days < self.MIN_DAYS
        return {
            **base,
            "status": "LOWVOL_SHADOW_ACCUMULATING" if accumulating else "LOWVOL_SHADOW_MEASURING",
            "cumulative_return_pct": round(100 * cum, 2),
            "annualized_sharpe": sharpe,
            "max_drawdown_pct": round(100 * mdd, 2),
            "benchmark": self.BENCHMARK,
            "benchmark_return_pct": round(100 * b_cum, 2) if b_cum is not None else None,
            "benchmark_max_drawdown_pct": round(100 * b_mdd, 2) if b_mdd is not None else None,
            "drawdown_ratio_vs_spy": dd_ratio,
            "verdict": (f"accumulating ({days}/{self.MIN_DAYS} days) — not enough live history to trust yet"
                        if accumulating else
                        f"measuring: live Sharpe {sharpe}, max DD {round(100*mdd,2)}% vs SPY "
                        f"{round(100*b_mdd,2) if b_mdd is not None else '?'}% "
                        f"(DD ratio {dd_ratio if dd_ratio is not None else '?'} — <1 means the low-vol "
                        f"thesis holds live)"),
        }
