"""Managed-futures SHADOW forward-test — measures the real edge with zero capital risk.

Why shadow: the live sleeve can only run LONG/FLAT at $10k (whole-share coarseness + shorts gated on
the place_order fix), so it can't test the thing that matters — the +0.02-to-carry diversification,
which comes entirely from the SHORT side. This tracker runs the FULL long/short TSMOM strategy on
paper (NO orders), marking a hypothetical daily P&L on settled bars, so EdgePersistence can watch the
real edge accumulate. When shorts go live (post place_order fix) or the book is larger, promote it.

Method mirrors ManagedFuturesResearchEngine exactly (multi-horizon TSMOM 63/126/252d sign blend,
inverse-vol to ~10% vol, monthly rebalance) so the live shadow numbers are directly comparable to the
backtest (net Sharpe ~0.41, carry corr +0.02). Driven by SETTLED daily bars (advances when a new
common bar appears — robust to when the scheduler cycle fires), no broker calls, self-gated once/bar.
"""

import csv
import json
import math
from datetime import datetime
from os import getenv
from pathlib import Path


class ManagedFuturesShadowEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/managed_futures")
    LEDGER = STATE / "shadow_ledger.jsonl"
    BASKET = ["QQQM", "IWM", "EFA", "EEM", "TLT", "IEF", "GLDM", "SLV", "DBC", "DBA"]
    LOOKBACKS = [63, 126, 252]
    VOL_WIN = 60
    TARGET_VOL = 0.10
    TRADING_DAYS = 252
    MIN_DAYS = 10                 # accumulating until this many marked days (mirrors EdgePersistence)
    CARRY_PROXY = "SVXY"          # the live carry sleeve's instrument — the correlation that matters

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def enabled():
        # default TRUE — the whole point is to accumulate live evidence while the sleeve is parked
        return (getenv("GREYLINE_MANAGED_FUTURES_SHADOW", "true") or "true").strip().lower() == "true"

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
        data = {s: self._closes(s) for s in self.BASKET}
        have = [s for s in self.BASKET if len(data[s]) > max(self.LOOKBACKS) + self.VOL_WIN]
        if not have:
            return [], [], {}
        common = sorted(set.intersection(*[set(data[s]) for s in have]))
        px = {s: [data[s][d] for d in common] for s in have}
        return have, common, px

    def _target_weights(self, have, px, i):
        """FULL long/short inverse-vol weights (the real strategy — shadow can short freely)."""
        per_asset_risk = self.TARGET_VOL / math.sqrt(len(have))
        w = {}
        for s in have:
            blend = sum(1.0 if px[s][i] > px[s][i - L] else -1.0 for L in self.LOOKBACKS) / len(self.LOOKBACKS)
            rets = [px[s][k] / px[s][k - 1] - 1 for k in range(max(1, i - self.VOL_WIN + 1), i + 1)]
            vol = max(self._stdev(rets) * math.sqrt(self.TRADING_DAYS), 0.05)
            w[s] = round(blend * per_asset_risk / vol, 5)
        return w

    def _last_entry(self):
        try:
            lines = self.LEDGER.read_text().splitlines()
            for ln in reversed(lines):
                if ln.strip():
                    return json.loads(ln)
        except Exception:
            pass
        return None

    def mark(self):
        """Advance one settled bar: book yesterday's weights' P&L, then (monthly) rebalance."""
        if not self.enabled():
            return {"status": "SHADOW_DISABLED", "acted": False}
        have, common, px = self._aligned()
        if len(common) < max(self.LOOKBACKS) + 2:
            return {"status": "SHADOW_INSUFFICIENT_DATA", "acted": False}
        i = len(common) - 1
        latest = common[i]
        last = self._last_entry()
        if last and str(last.get("date") or "") >= latest:
            return {"status": "SHADOW_NO_NEW_BAR", "acted": False, "date": latest}

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
        weights = self._target_weights(have, px, i) if rebalanced else last["weights"]

        entry = {"date": latest, "month": month, "weights": weights,
                 "closes": {s: round(closes_now[s], 4) for s in have},
                 "daily_return": daily_return, "rebalanced": rebalanced,
                 "marked_at": datetime.utcnow().isoformat()}
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            return {"status": "SHADOW_WRITE_FAILED", "acted": False, "error": repr(e)}
        return {"status": "SHADOW_MARKED", "acted": True, "date": latest,
                "daily_return": daily_return, "rebalanced": rebalanced}

    # ---- report --------------------------------------------------------------------------------

    def _entries(self):
        out = []
        try:
            for ln in self.LEDGER.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    @staticmethod
    def _pearson(a, b):
        n = min(len(a), len(b))
        if n < 3:
            return None
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a) / n, sum(b) / n
        cov = sum((a[k] - ma) * (b[k] - mb) for k in range(n))
        da = math.sqrt(sum((x - ma) ** 2 for x in a))
        db = math.sqrt(sum((x - mb) ** 2 for x in b))
        return round(cov / (da * db), 2) if da and db else None

    def report(self):
        entries = self._entries()
        rr = [(e["date"], e["daily_return"]) for e in entries if e.get("daily_return") is not None]
        days = len(rr)
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "days_tracked": days, "min_days": self.MIN_DAYS,
            "since": rr[0][0] if rr else None, "through": rr[-1][0] if rr else None,
            "backtest_reference": {"net_sharpe": 0.41, "carry_corr": 0.02},
            "note": ("SHADOW forward-test of the FULL long/short strategy — hypothetical P&L, no orders. "
                     "This is the real diversification test the live long/flat sleeve can't run."),
        }
        if days == 0:
            return {**base, "status": "SHADOW_NO_DATA",
                    "verdict": "no marks yet — starts on the next settled bar"}

        rets = [r for _, r in rr]
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rets:
            eq *= (1 + r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        sd = self._stdev(rets)
        sharpe = round((sum(rets) / days) / sd * math.sqrt(self.TRADING_DAYS), 2) if sd else 0.0

        # correlation to the live carry sleeve (SVXY) over the shadow dates — the thesis check
        svxy = self._closes(self.CARRY_PROXY)
        sd_dates = sorted(svxy)
        svxy_ret = {sd_dates[k]: svxy[sd_dates[k]] / svxy[sd_dates[k - 1]] - 1 for k in range(1, len(sd_dates))}
        paired = [(r, svxy_ret[d]) for d, r in rr if d in svxy_ret]
        carry_corr = self._pearson([p[0] for p in paired], [p[1] for p in paired]) if len(paired) >= 3 else None

        accumulating = days < self.MIN_DAYS
        return {
            **base,
            "status": "SHADOW_ACCUMULATING" if accumulating else "SHADOW_MEASURING",
            "cumulative_return_pct": round(100 * (eq - 1), 2),
            "annualized_sharpe": sharpe,
            "max_drawdown_pct": round(100 * mdd, 2),
            "live_carry_corr": carry_corr,
            "verdict": (f"accumulating ({days}/{self.MIN_DAYS} days) — not enough live history to trust yet"
                        if accumulating else
                        f"measuring: live Sharpe {sharpe} vs backtest 0.41; live carry-corr {carry_corr} "
                        f"vs backtest +0.02"),
        }
