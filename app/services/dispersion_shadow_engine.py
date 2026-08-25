"""Dispersion / correlation-risk-premium SHADOW — a ZERO-CAPITAL forward-test.

THE EDGE (the correlation risk premium): index options are priced RICHER than the vega-weighted single-name
options because portfolio hedgers pay up for index protection — so IMPLIED correlation systematically exceeds
REALIZED correlation. A dispersion trade harvests it: SHORT index vol, LONG single-name vol. It profits when the
components move more independently than the index options priced (realized corr < implied corr).

WHY IT'S THE RIGHT NEXT BUILD (2026-08-24): it DEEPENS GreyLine's one confirmed edge (the variance risk premium)
into a distinct, orthogonal dimension — the CORRELATION premium, not the variance premium — so it's the most
likely of the untested candidates to actually prove; and it DE-CONCENTRATES the short-vol book (a different
priced risk) rather than doubling down on pure short variance. It monetizes the UW vol surface (per-name IV a
price-only shop can't see).

THE SHADOW: each month it records the index IV and the basket's single-name IVs at entry -> IMPLIED correlation;
after a ~monthly hold it measures REALIZED correlation from the actual bars; the cohort's dispersion premium =
implied_corr - realized_corr, cost-netted for the (heavy) spread crossed on ~13 straddle legs, and judged on the
live edge court's rigorous bar (verdict_from_returns: cost-net, 95% CI, min-N). NO orders, NO budget.

HONEST CAVEATS the test must survive: (1) implied correlation here is the standard PROXY (index_var over
weighted-component_var) on a 12-name mega-cap basket vs SPY — a consistent MEASURE, not a tradable index-corr;
(2) dispersion is the tail-risk twin of short vol — correlation snaps to 1.0 in a crash (2008/2020/Mar-2026), so
it can bleed for months then lose big, which is exactly why it is cost-netted, cost-swept, and measured before
any capital; (3) the many-legged structure is genuinely expensive, so the cost assumption is generous."""

import csv
import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path

from app.services.ttl_cache import ttl_cached

STATE = Path("app/data/dispersion_shadow")
BARS = Path("app/data/historical")


def _rigorous_verdict(rets, min_n):
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class DispersionShadowEngine:

    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"

    INDEX = "SPY"
    BASKET = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "JPM", "LLY", "V", "XOM"]
    HOLD_DAYS = 21                 # ~monthly hold, matching ~30d IV
    MIN_COHORTS = 6                # ~6 monthly cohorts before the verdict is trustworthy
    PERIODS_PER_YEAR = 12
    COST_GRID = [0.0, 0.02, 0.05, 0.10]   # correlation-point round-trip cost sweep (dispersion is many-legged)

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_DISPERSION_SHADOW", "true") or "true").strip().lower() == "true"

    @classmethod
    def _cost(cls):
        try:
            return max(0.0, float(getenv("GREYLINE_DISPERSION_COST", "0.05")))
        except (TypeError, ValueError):
            return 0.05

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _today():
        return datetime.utcnow().date()

    @classmethod
    def _biz_days_elapsed(cls, start_iso):
        try:
            start = date.fromisoformat(str(start_iso)[:10])
        except (ValueError, TypeError):
            return 0
        today = cls._today()
        if today <= start:
            return 0
        n, d = 0, start
        while d < today:
            d = d + timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    # ---- IV (UW) + realized vol (bars) ---------------------------------------------------------
    def _ivs(self, syms):
        """{symbol: implied vol} from UW volatility/stats. Best-effort; names without an IV drop out."""
        import os
        import requests
        key = os.getenv("UNUSUAL_WHALES_API_KEY")
        if not key:
            return {}
        base = os.getenv("UNUSUAL_WHALES_BASE_URL") or "https://api.unusualwhales.com"
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
        out = {}
        for t in syms:
            try:
                r = s.get(f"{base}/api/stock/{t}/volatility/stats", timeout=12)
                iv = self._f(((r.json() or {}).get("data") or {}).get("iv"))
                if iv and iv > 0:
                    out[t] = iv
            except Exception:
                continue
        return out

    @classmethod
    def _realized_vol(cls, sym, start_iso, end_iso):
        """Annualized realized vol of `sym` over (start, end] — std of daily log returns x sqrt(252) from bars."""
        closes = []
        try:
            with open(BARS / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    d = str(r.get("date"))[:10]
                    if start_iso <= d <= end_iso:
                        c = cls._f(r.get("close"))
                        if c and c > 0:
                            closes.append((d, c))
        except Exception:
            return None
        closes.sort()
        if len(closes) < 4:
            return None
        rets = [math.log(closes[i][1] / closes[i - 1][1]) for i in range(1, len(closes))]
        if len(rets) < 3:
            return None
        m = sum(rets) / len(rets)
        var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
        return math.sqrt(var * 252)

    @staticmethod
    def _corr(index_vol, component_vols):
        """Proxy (dirty) correlation = index_var / (equal-weight mean component vol)^2 — the standard dispersion
        implied/realized correlation under the all-pairwise-equal assumption. None if inputs missing."""
        comp = [v for v in component_vols if v and v > 0]
        if not index_vol or index_vol <= 0 or not comp:
            return None
        avg = sum(comp) / len(comp)
        return round((index_vol / avg) ** 2, 6) if avg > 0 else None

    # ---- state ---------------------------------------------------------------------------------
    def _load_open(self):
        try:
            return json.loads(self.OPEN.read_text())
        except Exception:
            return []

    def _save_open(self, cohorts):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            self.OPEN.write_text(json.dumps(cohorts))
        except Exception:
            pass

    def _append_closed(self, rec):
        STATE.mkdir(parents=True, exist_ok=True)
        with open(self.CLOSED, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def _closed(self):
        out = []
        try:
            for ln in self.CLOSED.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    # ---- mark ----------------------------------------------------------------------------------
    def mark(self):
        """Settle a matured monthly cohort (implied corr at entry vs realized corr over the hold), then open a
        fresh NON-OVERLAPPING cohort recording today's index + basket IVs. NO orders, NO budget."""
        if not self.enabled():
            return {"status": "DISPERSION_SHADOW_DISABLED", "acted": False}
        from app.services.shadow_tradeability_gate import equity_session_open
        rth = equity_session_open()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            opened, today = co.get("opened"), self._today().isoformat()
            idx_rv = self._realized_vol(self.INDEX, opened, today)
            comp_rv = [self._realized_vol(s, opened, today) for s in co.get("basket", self.BASKET)]
            realized_corr = self._corr(idx_rv, comp_rv)
            implied_corr = self._f(co.get("implied_corr"))
            if realized_corr is None or implied_corr is None:
                still_open.append(co)                 # not enough realized data yet -> settle next cycle
                continue
            premium = round(implied_corr - realized_corr, 6)        # >0 = correlation premium harvested
            rec = {"opened": opened, "settled_at": datetime.utcnow().isoformat(),
                   "implied_corr": round(implied_corr, 4), "realized_corr": round(realized_corr, 4),
                   "dispersion_premium": premium, "cost": self._cost(),
                   "net_return": round(premium - self._cost(), 6),
                   "index_iv_entry": co.get("index_iv"), "index_rv": round(idx_rv, 4) if idx_rv else None,
                   "n_components": len([v for v in comp_rv if v])}
            self._append_closed(rec)
            closed_now.append(rec)

        opened = None
        if not still_open and rth:                    # non-overlapping AND only during a real session
            ivs = self._ivs([self.INDEX] + self.BASKET)
            idx_iv = ivs.get(self.INDEX)
            comp_ivs = {s: ivs[s] for s in self.BASKET if s in ivs}
            implied_corr = self._corr(idx_iv, list(comp_ivs.values()))
            if idx_iv and implied_corr is not None and len(comp_ivs) >= max(4, len(self.BASKET) // 2):
                opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                          "index_iv": round(idx_iv, 4), "component_ivs": {k: round(v, 4) for k, v in comp_ivs.items()},
                          "implied_corr": round(implied_corr, 4), "basket": list(comp_ivs.keys())}
                still_open.append(opened)

        self._save_open(still_open)
        return {"status": "DISPERSION_SHADOW_MARKED", "acted": bool(closed_now or opened),
                "cohorts_closed": len(closed_now), "cohort_opened": bool(opened), "open_cohorts": len(still_open)}

    # ---- report --------------------------------------------------------------------------------
    @staticmethod
    def _stats(rets):
        n = len(rets)
        if n < 1:
            return {"n": 0}
        mean = sum(rets) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1)) if n > 1 else 0.0
        return {"n": n, "mean_corr_points": round(mean, 4),
                "sharpe_annualized": round(mean / sd * math.sqrt(DispersionShadowEngine.PERIODS_PER_YEAR), 2) if sd else None,
                "win_rate": round(sum(1 for r in rets if r > 0) / n, 3)}

    def _cost_sweep(self, gross):
        out = []
        for c in self.COST_GRID:
            net = [g - c for g in gross]
            m = sum(net) / len(net) if net else 0.0
            out.append({"cost_corr_points": c, "net_mean_corr_points": round(m, 4)})
        return out

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self):
        closed = self._closed()
        gross = [c["dispersion_premium"] for c in closed if c.get("dispersion_premium") is not None]
        net = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(net)
        open_co = self._load_open()
        cur = open_co[0] if open_co else None
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "DispersionShadowEngine", "index": self.INDEX, "basket_size": len(self.BASKET),
                "signal": "dispersion: short index vol / long single-name vol — harvest implied-minus-realized correlation",
                "hold_days": self.HOLD_DAYS, "cost_corr_points": self._cost(),
                "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
                "rigorous_verdict": _rigorous_verdict(net, self.MIN_COHORTS),
                "current_cohort": ({"opened": cur.get("opened"), "implied_corr": cur.get("implied_corr"),
                                    "index_iv": cur.get("index_iv"),
                                    "days_to_settle": max(0, self.HOLD_DAYS - self._biz_days_elapsed(cur.get("opened")))}
                                   if cur else None),
                "note": ("ZERO-capital correlation-premium forward-test: implied corr (index IV vs basket IV) minus "
                         "realized corr over a monthly hold, cost-net, judged on the court's bar. Deepens the VRP "
                         "franchise into the correlation dimension; tail-risky (corr->1 in crashes). NO orders.")}
        if n == 0:
            return {**base, "status": "DISPERSION_SHADOW_NO_DATA",
                    "verdict": (f"1 cohort open (implied corr {cur.get('implied_corr')}) — first settles ~{self.HOLD_DAYS} "
                                f"business days after opening" if cur else "no cohort yet — opens next mark")}
        accumulating = n < self.MIN_COHORTS
        st = self._stats(net)
        return {**base,
                "status": "DISPERSION_SHADOW_ACCUMULATING" if accumulating else "DISPERSION_SHADOW_MEASURING",
                "net_stats": st, "gross_stats": self._stats(gross), "cost_sweep": self._cost_sweep(gross),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} monthly cohorts) — not enough yet"
                            if accumulating else
                            f"measuring: correlation premium net mean {st['mean_corr_points']} pts, Sharpe "
                            f"{st['sharpe_annualized']} over {n} months")}
