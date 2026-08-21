"""Option-implied volatility SKEW SHADOW — a ZERO-CAPITAL, market-neutral forward-test.

THE EDGE (Xing-Zhang-Zhao 2010; Cremers-Weinbaum 2010; Bali-Hu-Murray): the shape of a name's option-implied
volatility smile predicts its future stock return. Steep put skew (puts richer than calls — a negative 25-delta
RISK REVERSAL) forecasts LOW future returns; a call-rich smile forecasts HIGH returns. Rank the optionable
universe by 25-delta risk reversal, go LONG the top-K (least put-skewed) and SHORT the bottom-K (most
put-skewed): a market-neutral cross-sectional spread.

WHY IT'S A GOOD NEXT TEST (elite-OS literature survey 2026-08-20): it monetizes GreyLine's single biggest data
asset — UW serves per-name 25-delta risk reversal directly (/historical-risk-reversal-skew), which a price-only
shop cannot build. It is ORTHOGONAL to VRP (information IN options predicting the STOCK, not a vol-premium
harvest), and it is traded as CHEAP EQUITY (hold the underlying, flat the option), so it sidesteps the option
round-trip cost that killed every directional OPTION edge GreyLine tested. Monthly-ish signal, weekly hold =
low turnover, the class of anomaly that survives costs (Novy-Marx & Velikov).

THE SHADOW: weekly it reads each name's latest 25-delta risk reversal at a ~monthly expiry, forms a
top-K-long / bottom-K-short cohort, settles at LIVE EQUITY quotes a week later as a dollar-neutral SPREAD
(mean long return − mean short return, cost charged on both sleeves), and judges the settled cohort returns on
the live edge court's rigorous bar (verdict_from_returns: cost-net, 95% CI, min-N). NO orders, NO budget.

HONEST CAVEATS: the academic result is cleanest on single names (index/sector ETFs carry a STRUCTURAL skew), so
the universe skews toward single names but is not purified; and skew has a slow-moving structural component that
a pure cross-sectional rank does not fully neutralize. The forward series is the honest, cost-net test."""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path

from app.services.ttl_cache import ttl_cached


def _rigorous_verdict(rets, min_n):
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class IvSkewShadowEngine:

    STATE = Path("app/data/iv_skew_shadow")
    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"

    TOP_K = 8                      # long the top-K risk reversal / short the bottom-K
    HOLD_DAYS = 5                  # non-overlapping weekly hold, settle at live equity quotes
    MIN_COHORTS = 8                # ~2 months of weekly cohorts before the verdict is trustworthy
    PERIODS_PER_YEAR = 252 / 5
    DEFAULT_UNIVERSE_SIZE = 80     # cap the (liquidity-ordered) optionable universe -> bounded UW calls / week

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_IV_SKEW_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _cost_roundtrip():
        try:
            return float(getenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")) / 10000.0
        except (TypeError, ValueError):
            return 10 / 10000.0

    @classmethod
    def _universe_size(cls):
        try:
            return max(2 * cls.TOP_K, int(getenv("GREYLINE_IV_SKEW_UNIVERSE_SIZE", "") or cls.DEFAULT_UNIVERSE_SIZE))
        except (TypeError, ValueError):
            return cls.DEFAULT_UNIVERSE_SIZE

    @staticmethod
    def _f2(v):
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

    # ---- universe + skew signal (UW) -----------------------------------------------------------
    # Index/sector/commodity/bond ETFs carry a STRUCTURAL skew (correlation + crash hedging), so the single-name
    # skew->return result does not apply to them cleanly — exclude by the universe's own issue_type metadata.
    _EXCLUDED_ISSUE_TYPES = {"ETF", "ETN", "FUND", "CLOSED-END FUND", "CLOSED END FUND"}

    def _universe(self):
        """The liquidity-ordered optionable SINGLE-NAME universe (ETFs excluded), capped. Override with
        GREYLINE_IV_SKEW_UNIVERSE (comma-sep; taken verbatim, no ETF filter)."""
        raw = (getenv("GREYLINE_IV_SKEW_UNIVERSE", "") or "").strip()
        if raw:
            return [s.strip().upper() for s in raw.split(",") if s.strip()][: self._universe_size()]
        try:
            from app.services.optionable_universe_engine import OptionableUniverseEngine
            rows = (OptionableUniverseEngine().report() or {}).get("rows") or []
            names = [str(r.get("ticker")).upper() for r in rows
                     if r.get("ticker") and str(r.get("issue_type") or "").strip().upper() not in self._EXCLUDED_ISSUE_TYPES]
            if names:
                return names[: self._universe_size()]
            # fallback: names() has no issue_type — better a mixed universe than none
            return [str(s).upper() for s in (OptionableUniverseEngine().names() or [])][: self._universe_size()]
        except Exception:
            return []

    @staticmethod
    def _monthly_expiry():
        try:
            from app.services.uw_option_chain_engine import UWOptionChainEngine
            return UWOptionChainEngine.monthly_expiry(target_dte=42)
        except Exception:
            return None

    def _risk_reversal(self, session, base, tkr, expiry):
        """Latest 25-delta risk reversal for a name (call-side minus put-side; steeper put skew = more negative).
        Tries the ~monthly expiry, then the undated series. None on any failure."""
        for params in ([{"expiry": expiry}] if expiry else []) + [{}]:
            try:
                r = session.get(f"{base}/api/stock/{tkr}/historical-risk-reversal-skew", params=params, timeout=12)
                if r.status_code != 200:
                    continue
                data = [x for x in ((r.json() or {}).get("data") or []) if x.get("risk_reversal") is not None]
                if data:
                    return self._f2(data[-1]["risk_reversal"])
            except Exception:
                continue
        return None

    def _skew_by_symbol(self, syms):
        """{symbol: latest 25d risk reversal} for the universe, from UW. Best-effort; names without a reading drop."""
        import os
        import requests
        key = os.getenv("UNUSUAL_WHALES_API_KEY")
        if not key:
            return {}
        base = os.getenv("UNUSUAL_WHALES_BASE_URL") or "https://api.unusualwhales.com"
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
        expiry = self._monthly_expiry()
        out = {}
        for sym in syms:
            rr = self._risk_reversal(s, base, sym, expiry)
            if rr is not None:
                out[sym] = rr
        return out

    def _signal_ls(self):
        """Rank the universe by risk reversal; top-K LONG (least put-skewed) / bottom-K SHORT (most put-skewed).
        None if fewer than 2*TOP_K names have a reading."""
        skew = self._skew_by_symbol(self._universe())
        ranked = sorted(skew.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) < 2 * self.TOP_K:
            return None
        long = [{"symbol": s, "risk_reversal": round(v, 6)} for s, v in ranked[: self.TOP_K]]
        short = [{"symbol": s, "risk_reversal": round(v, 6)} for s, v in ranked[-self.TOP_K:]]
        return {"long": long, "short": short}

    def _live_prices(self, syms):
        syms = sorted({str(s or "").upper() for s in syms if s})
        if not syms:
            return {}
        out = {}
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            quotes = TradeStationQuoteLiveEngine().get_quotes(syms) or {}
        except Exception:
            return {}
        for s in syms:
            q = quotes.get(s) or {}
            row = (((q.get("response_json") or {}).get("Quotes") or [{}]) or [{}])[0]
            px = self._f2(row.get("Last")) or self._f2(row.get("Close"))
            if px and px > 0:
                out[s] = px
        return out

    # ---- state ---------------------------------------------------------------------------------
    def _load_open(self):
        try:
            return json.loads(self.OPEN.read_text())
        except Exception:
            return []

    def _save_open(self, cohorts):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.OPEN.write_text(json.dumps(cohorts))
        except Exception:
            pass

    def _append_closed(self, rec):
        self.STATE.mkdir(parents=True, exist_ok=True)
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
        """Settle a matured weekly cohort as a dollar-neutral SPREAD (mean long − mean short, both sleeves
        cost-crossed), then open a fresh non-overlapping top-K-long / bottom-K-short skew cohort. NO orders."""
        if not self.enabled():
            return {"status": "IV_SKEW_SHADOW_DISABLED", "acted": False}
        from app.services.shadow_tradeability_gate import equity_session_open
        rth = equity_session_open()
        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            if not rth:
                still_open.append(co)
                continue
            legs = co.get("legs", [])
            prices = self._live_prices([l["symbol"] for l in legs])
            settled = []
            for leg in legs:
                px = prices.get(str(leg["symbol"]).upper())
                ec = self._f2(leg.get("entry_close"))
                if px and ec and ec > 0:
                    settled.append({**leg, "exit_close": round(px, 4), "gross_return": round(px / ec - 1.0, 6)})
            if len(settled) < len(legs):
                still_open.append(co)
                continue
            longs = [l["gross_return"] for l in settled if l["side"] == "BUY"]
            shorts = [l["gross_return"] for l in settled if l["side"] == "SELL"]
            if not longs or not shorts:
                still_open.append(co)
                continue
            spread = sum(longs) / len(longs) - sum(shorts) / len(shorts)
            rec = {"opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                   "n_long": len(longs), "n_short": len(shorts), "cost_roundtrip_bps": round(cost * 10000, 2),
                   "gross_spread": round(spread, 6), "net_return": round(spread - 2 * cost, 6),
                   "legs": [{"symbol": l["symbol"], "side": l["side"], "gross_return": l["gross_return"]} for l in settled]}
            self._append_closed(rec)
            closed_now.append(rec)

        opened = None
        if not still_open and rth:
            tg = self._signal_ls()
            if tg:
                live = self._live_prices([p["symbol"] for p in tg["long"] + tg["short"]])
                legs = []
                for side, picks in (("BUY", tg["long"]), ("SELL", tg["short"])):
                    for p in picks:
                        sym = str(p["symbol"]).upper()
                        entry = live.get(sym)
                        if entry:
                            legs.append({"symbol": sym, "side": side, "entry_close": round(entry, 4),
                                         "risk_reversal": p["risk_reversal"]})
                n_long = sum(1 for l in legs if l["side"] == "BUY")
                n_short = sum(1 for l in legs if l["side"] == "SELL")
                if n_long >= 3 and n_short >= 3:
                    opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                              "top_k": self.TOP_K, "legs": legs}
                    still_open.append(opened)

        self._save_open(still_open)
        return {"status": "IV_SKEW_SHADOW_MARKED", "acted": bool(closed_now or opened),
                "cohorts_closed": len(closed_now), "cohort_opened": bool(opened), "open_cohorts": len(still_open)}

    # ---- positions + report --------------------------------------------------------------------
    def open_positions(self):
        cohorts = self._load_open()
        prices = self._live_prices([l["symbol"] for co in cohorts for l in co.get("legs", [])])
        rows = []
        for co in cohorts:
            held = self._biz_days_elapsed(co.get("opened"))
            for leg in co.get("legs", []):
                ec = self._f2(leg.get("entry_close")) or 0.0
                cur = prices.get(str(leg["symbol"]).upper())
                side = str(leg.get("side") or "BUY").upper()
                pct = (round(100 * ((cur / ec - 1.0) if side == "BUY" else (ec / cur - 1.0)), 2)
                       if (cur and ec > 0) else None)
                rows.append({"symbol": leg["symbol"], "side": side, "entry_date": co.get("opened"),
                             "entry_close": round(ec, 4) if ec else None,
                             "live_last": round(cur, 4) if cur else None, "unrealized_pct": pct,
                             "risk_reversal": leg.get("risk_reversal"),
                             "days_held": held, "days_to_settle": max(0, self.HOLD_DAYS - held)})
        rows.sort(key=lambda r: (r.get("risk_reversal") if r.get("risk_reversal") is not None else 0), reverse=True)
        return rows

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self):
        from app.services.shadow_contract_sizing import enrich_open_rows
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        positions = enrich_open_rows(self.open_positions())
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "IvSkewShadowEngine",
                "signal": f"25-delta risk-reversal skew · top-{self.TOP_K} long / bottom-{self.TOP_K} short · market-neutral",
                "universe_size": len(self._universe()), "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
                "open_cohorts": len(self._load_open()), "open_positions": positions,
                "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
                "rigorous_verdict": _rigorous_verdict(rets, self.MIN_COHORTS),
                "note": ("ZERO-capital market-neutral forward-test: skew (25d risk reversal) predicts the stock "
                         "(Xing-Zhang-Zhao / Cremers-Weinbaum). Long least-put-skewed, short most-put-skewed; "
                         "traded as cheap EQUITY (sidesteps option cost), judged on the court's bar. NO orders.")}
        if n == 0:
            return {**base, "status": "IV_SKEW_SHADOW_NO_DATA",
                    "verdict": (f"{len(positions)} open ({sum(1 for p in positions if p['side']=='BUY')} long / "
                                f"{sum(1 for p in positions if p['side']=='SELL')} short) — first weekly spread "
                                f"cohort settles ~{self.HOLD_DAYS} business days after opening" if positions else
                                "no cohorts yet — the first opens next mark on the skew-ranked universe")}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {**base,
                "status": "IV_SKEW_SHADOW_ACCUMULATING" if accumulating else "IV_SKEW_SHADOW_MEASURING",
                "cumulative_return_pct": round(100 * (eq - 1), 2),
                "avg_net_return_per_week_bps": round(mean * 10000, 2),
                "annualized_sharpe": sharpe, "win_rate_pct": round(100 * wins / n, 1),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} weekly spread cohorts) — not enough yet"
                            if accumulating else
                            f"measuring: market-neutral skew net Sharpe {sharpe} over {n} weeks")}
