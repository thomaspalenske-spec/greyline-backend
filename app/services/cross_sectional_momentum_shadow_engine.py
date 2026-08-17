"""Cross-sectional dual-momentum SHADOW forward-test — measures the sleeve's real edge with zero capital
risk and, crucially, WITHOUT the live sleeve-position collision.

Why shadow: the live sleeve's ETF universe overlaps the trend sleeve's basket, so sizing it against broker
totals would make the two fight over shared ETFs (it would liquidate trend's QQQM/IWM/EFA/DBC). Until the
per-sleeve position-accounting refactor lands, this tracker runs the FULL strategy on paper (NO orders,
isolated book) — marking a hypothetical daily P&L on settled bars so the edge court can watch the real edge
accumulate. When per-sleeve sizing is live + validated, promote it.

Method mirrors CrossSectionalMomentumEngine exactly (12-1 cross-sectional rank, top-N that clear the
absolute-momentum filter, equal-weight, monthly rebalance) so the shadow numbers are directly comparable.
Long-only: the un-selected weight sits in cash (earns 0 here). Driven by SETTLED daily bars (advances when a
new common bar appears — robust to when the scheduler fires), no broker calls, self-gated once/bar.
"""

import csv
import json
import math
from datetime import datetime
from os import getenv
from pathlib import Path


class CrossSectionalMomentumShadowEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/xs_momentum")
    LEDGER = STATE / "shadow_ledger.jsonl"
    UNIVERSE = ["QQQM", "IWM", "EFA", "EEM", "TLT", "IEF", "HYG", "GLDM", "DBC", "VNQ"]
    LOOKBACK_DAYS = 252
    SKIP_DAYS = 21
    TOP_N = 4
    MIN_ABS_MOM = 0.0
    VOL_WIN = 60
    TRADING_DAYS = 252
    MIN_DAYS = 10

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def enabled():
        # default TRUE — the point is to accumulate live evidence while the live sleeve is parked
        return (getenv("GREYLINE_XSMOM_SHADOW", "true") or "true").strip().lower() == "true"

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
        data = {s: self._closes(s) for s in self.UNIVERSE}
        have = [s for s in self.UNIVERSE if len(data[s]) > self.LOOKBACK_DAYS + self.SKIP_DAYS + 2]
        if not have:
            return [], [], {}
        common = sorted(set.intersection(*[set(data[s]) for s in have]))
        px = {s: [data[s][d] for d in common] for s in have}
        return have, common, px

    def _selection_weights(self, have, px, i):
        """12-1 cross-sectional rank at bar i; equal-weight the top-N clearing the absolute filter. Long-
        only — the remainder is cash (weight sum < 1 -> the rest earns 0)."""
        moms = {}
        for s in have:
            old = px[s][i - self.LOOKBACK_DAYS]
            recent = px[s][i - self.SKIP_DAYS]
            moms[s] = (recent / old - 1.0) if old > 0 else -9.0
        ranked = sorted(moms.items(), key=lambda kv: kv[1], reverse=True)
        selected = [s for s, m in ranked if m > self.MIN_ABS_MOM][: self.TOP_N]
        w = {s: round(1.0 / len(selected), 5) for s in selected} if selected else {}
        return w, {s: round(moms[s], 4) for s in have}

    def _last_entry(self):
        try:
            for ln in reversed(self.LEDGER.read_text().splitlines()):
                if ln.strip():
                    return json.loads(ln)
        except Exception:
            pass
        return None

    def mark(self):
        """Advance one settled bar: book yesterday's weights' P&L, then (monthly) re-rank."""
        if not self.enabled():
            return {"status": "XSMOM_SHADOW_DISABLED", "acted": False}
        have, common, px = self._aligned()
        if len(common) < self.LOOKBACK_DAYS + 2:
            return {"status": "XSMOM_SHADOW_INSUFFICIENT_DATA", "acted": False}
        i = len(common) - 1
        latest = common[i]
        last = self._last_entry()
        if last and str(last.get("date") or "") >= latest:
            return {"status": "XSMOM_SHADOW_NO_NEW_BAR", "acted": False, "date": latest}

        closes_now = {s: px[s][i] for s in have}
        daily_return = None
        if last and last.get("closes") and last.get("weights"):
            dr = 0.0
            for s, w in last["weights"].items():
                pc = last["closes"].get(s)
                if pc and s in closes_now:
                    dr += w * (closes_now[s] / pc - 1)
            daily_return = round(dr, 6)

        month = latest[:7]
        rebalanced = not (last and last.get("month") == month and last.get("weights") is not None)
        if rebalanced:
            weights, moms = self._selection_weights(have, px, i)
        else:
            weights, moms = last["weights"], last.get("moms", {})

        entry = {"date": latest, "month": month, "weights": weights, "moms": moms,
                 "selected": list(weights.keys()),
                 "closes": {s: round(closes_now[s], 4) for s in have},
                 "daily_return": daily_return, "rebalanced": rebalanced,
                 "marked_at": datetime.utcnow().isoformat()}
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            return {"status": "XSMOM_SHADOW_WRITE_FAILED", "acted": False, "error": repr(e)}
        return {"status": "XSMOM_SHADOW_MARKED", "acted": True, "date": latest,
                "daily_return": daily_return, "rebalanced": rebalanced, "selected": entry["selected"]}

    def _entries(self):
        out = []
        try:
            for ln in self.LEDGER.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    def report(self):
        entries = self._entries()
        rr = [(e["date"], e["daily_return"]) for e in entries if e.get("daily_return") is not None]
        days = len(rr)
        last = self._last_entry()
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "days_tracked": days, "min_days": self.MIN_DAYS,
                "since": rr[0][0] if rr else None, "through": rr[-1][0] if rr else None,
                "current_holdings": (last or {}).get("selected"),
                "note": ("SHADOW forward-test of the cross-sectional dual-momentum sleeve — hypothetical "
                         "P&L, NO orders (avoids the live sleeve-position collision with trend over shared "
                         "ETFs). Promote to live once per-sleeve position accounting is validated."),
                "status": "XS_MOMENTUM_SHADOW_REPORT"}
        if days == 0:
            return {**base, "verdict": "no marks yet — starts on the next settled bar"}
        rets = [r for _, r in rr]
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rets:
            eq *= (1 + r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        sd = self._stdev(rets)
        sharpe = round((sum(rets) / days) / sd * math.sqrt(self.TRADING_DAYS), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        return {**base,
                "cumulative_return_pct": round((eq - 1) * 100, 2),
                "annualized_sharpe": sharpe, "max_drawdown_pct": round(mdd * 100, 2),
                "win_rate": round(wins / days, 2),
                "verdict": (f"ACCUMULATING ({days}/{self.MIN_DAYS} days)" if days < self.MIN_DAYS
                            else f"tracking — Sharpe {sharpe}, cum {round((eq-1)*100,2)}%")}
