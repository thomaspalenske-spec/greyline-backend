"""Extended-ETF SHADOW forward-test — the measurement layer for the 52-ETF extended universe.

The 2026-08-12 scan added 52 ETFs as TRACKED CANDIDATES and backfilled their bars, but nothing measured
them. This is that measurement: a ZERO-capital cross-sectional-momentum (relative-strength) forward-test on
the tradeable ETF universe — rank them by trailing return off the backfilled bars, hold the top-K equal-
weight for a non-overlapping week, settle at LIVE quotes, net the round-trip cost, and judge the settled
cohort returns on the SAME rigorous bar the live edge court uses (small-sample-t 95% CI + min-N).

NO orders, NO budget. This is how the new ETFs earn their way toward a verdict before any capital is
committed — a bigger universe is more candidates, not more edge, and this is where a candidate proves it.
"""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path
from app.services.ttl_cache import ttl_cached


def _rigorous_verdict(rets, min_n):
    """Judge on the SAME small-sample-t 95% CI + min-N bar as the live court, so 'proven' means what a
    live sleeve's would. Best-effort — a soft summary still ships if the import ever fails."""
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class ExtendedEtfShadowEngine:

    STATE = Path("app/data/extended_etf_shadow")
    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"
    # Parallel LONG/SHORT track: top-K long / bottom-K short, market-neutral. It runs alongside the long-only
    # track (its own files, never touching it) so we measure the pure cross-sectional SPREAD — the momentum
    # edge with equity beta netted out — vs the long-only basket which is mostly beta. Comparing the two
    # isolates alpha from beta.
    OPEN_LS = STATE / "open_cohort_ls.json"
    CLOSED_LS = STATE / "closed_cohorts_ls.jsonl"
    HIST = "app/data/historical"

    LOOKBACK = 63                 # ~3-month trailing return = the cross-sectional momentum signal
    TOP_K = 6                     # long the top-K by relative strength (long-only; diversified ETFs)
    HOLD_DAYS = 5                 # non-overlapping weekly hold, settle at live quotes
    MIN_COHORTS = 8               # ~2 months of weekly cohorts before the verdict is trustworthy
    PERIODS_PER_YEAR = 252 / 5

    @staticmethod
    def enabled():
        # default TRUE — measurement only (never an order), so 'on' costs nothing and commits no budget.
        return (getenv("GREYLINE_EXTENDED_ETF_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _ls_enabled():
        # the market-neutral long/short track (default on); can be silenced without killing the long-only track.
        return (getenv("GREYLINE_EXTENDED_ETF_SHADOW_LS", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _cost_roundtrip():
        try:
            return float(getenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")) / 10000.0
        except (TypeError, ValueError):
            return 10 / 10000.0

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

    # ---- universe + signal (from the backfilled bars) ------------------------------------------
    def _universe(self):
        try:
            from app.services.extended_etf_universe_engine import ExtendedEtfUniverseEngine
            syms = ExtendedEtfUniverseEngine.symbols(include_caution=False)
        except Exception:
            return []
        import os
        return [s for s in syms if os.path.exists(f"{self.HIST}/{s}_daily.csv")]

    def _trailing_return(self, sym):
        """LOOKBACK-day trailing return from the disk bars, or None. close[-1]/close[-1-LOOKBACK] - 1."""
        try:
            import csv
            closes = [self._f2(r.get("close")) for r in csv.DictReader(open(f"{self.HIST}/{sym}_daily.csv"))]
            closes = [c for c in closes if c and c > 0]
        except Exception:
            return None
        if len(closes) < self.LOOKBACK + 1:
            return None
        past = closes[-1 - self.LOOKBACK]
        return (closes[-1] / past - 1.0) if past > 0 else None

    def _signal_targets(self):
        """Rank the ETF universe by trailing return (desc); return the top-K with a valid signal."""
        scored = [(s, self._trailing_return(s)) for s in self._universe()]
        scored = [(s, r) for s, r in scored if r is not None]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [{"symbol": s, "trailing_return": round(r, 6)} for s, r in scored[:self.TOP_K]]

    def _signal_targets_ls(self):
        """Rank the universe by trailing return; return the top-K to go LONG and the bottom-K to go SHORT.
        None if the universe is too small to form two disjoint sleeves (< 2*TOP_K names with a signal)."""
        scored = [(s, self._trailing_return(s)) for s in self._universe()]
        scored = [(s, r) for s, r in scored if r is not None]
        if len(scored) < 2 * self.TOP_K:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        top = [{"symbol": s, "trailing_return": round(r, 6)} for s, r in scored[:self.TOP_K]]
        bot = [{"symbol": s, "trailing_return": round(r, 6)} for s, r in scored[-self.TOP_K:]]
        return {"long": top, "short": bot}

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

    # ---- state (path defaults to the long-only track; pass OPEN_LS/CLOSED_LS for the L/S track) ---
    def _load_open(self, path=None):
        try:
            return json.loads((path or self.OPEN).read_text())
        except Exception:
            return []

    def _save_open(self, cohorts, path=None):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            (path or self.OPEN).write_text(json.dumps(cohorts))
        except Exception:
            pass

    def _append_closed(self, rec, path=None):
        self.STATE.mkdir(parents=True, exist_ok=True)
        with open(path or self.CLOSED, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def _closed(self, path=None):
        out = []
        try:
            for ln in (path or self.CLOSED).read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    # ---- mark ----------------------------------------------------------------------------------
    def mark(self):
        """Settle any cohort past its weekly hold (live quotes), then open a fresh NON-OVERLAPPING cohort
        long the top-K relative-strength ETFs at live entry. NO orders, NO budget."""
        if not self.enabled():
            return {"status": "ETF_SHADOW_DISABLED", "acted": False}
        # THE RULE: only open/settle when it could actually have executed on TradeStation (equity session).
        from app.services.shadow_tradeability_gate import equity_session_open
        rth = equity_session_open()
        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            legs = co.get("legs", [])
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            if not rth:
                still_open.append(co)                 # matured, but settle only at a live quote -> next RTH
                continue
            prices = self._live_prices([l["symbol"] for l in legs])
            settled = []
            for leg in legs:
                px = prices.get(str(leg["symbol"]).upper())
                ec = self._f2(leg.get("entry_close"))
                if px and ec and ec > 0:
                    settled.append({**leg, "exit_close": round(px, 4), "gross_return": round(px / ec - 1.0, 6)})
            if len(settled) < len(legs):
                still_open.append(co)                 # quote gap — settle when quotes return, never partial
                continue
            gross_mean = sum(l["gross_return"] for l in settled) / len(settled)
            rec = {"opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                   "n_legs": len(settled), "cost_roundtrip_bps": round(cost * 10000, 2),
                   "gross_return": round(gross_mean, 6), "net_return": round(gross_mean - cost, 6),
                   "legs": [{"symbol": l["symbol"], "gross_return": l["gross_return"]} for l in settled]}
            self._append_closed(rec)
            closed_now.append(rec)

        opened = None
        if not still_open and rth:                     # non-overlapping AND only during a real session
            picks = self._signal_targets()
            live = self._live_prices([p["symbol"] for p in picks])
            legs = []
            for p in picks:
                sym = str(p["symbol"]).upper()
                entry = live.get(sym)
                if entry:                              # only enter names we can price live (never fabricate)
                    legs.append({"symbol": sym, "side": "BUY", "entry_close": round(entry, 4),
                                 "trailing_return": p["trailing_return"]})
            if len(legs) >= 3:                         # need a real basket, not one lucky name
                opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                          "top_k": self.TOP_K, "legs": legs}
                still_open.append(opened)

        self._save_open(still_open)
        ls = self._mark_ls(rth, cost) if self._ls_enabled() else {"skipped": True}
        return {"status": "ETF_SHADOW_MARKED",
                "acted": bool(closed_now or opened or ls.get("cohorts_closed") or ls.get("cohort_opened")),
                "cohorts_closed": len(closed_now), "cohort_opened": bool(opened),
                "open_cohorts": len(still_open), "long_short": ls}

    def _mark_ls(self, rth, cost):
        """The market-neutral twin of mark(): settle any matured L/S cohort as a SPREAD (mean long return −
        mean short return, both legs cost-crossed), then open a fresh non-overlapping top-K-long / bottom-K-short
        cohort. Its own state files — never touches the long-only track. NO orders, NO budget."""
        cohorts = self._load_open(self.OPEN_LS)
        closed_now, still_open = [], []
        for co in cohorts:
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            if not rth:
                still_open.append(co)                 # matured, but settle only at a live quote -> next RTH
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
                still_open.append(co)                 # quote gap — settle whole or not at all
                continue
            longs = [l["gross_return"] for l in settled if l["side"] == "BUY"]
            shorts = [l["gross_return"] for l in settled if l["side"] == "SELL"]
            if not longs or not shorts:
                still_open.append(co)                 # need both sleeves to form a spread
                continue
            spread = sum(longs) / len(longs) - sum(shorts) / len(shorts)   # dollar-neutral long/short return
            rec = {"opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                   "n_long": len(longs), "n_short": len(shorts), "cost_roundtrip_bps": round(cost * 10000, 2),
                   "gross_spread": round(spread, 6),
                   "net_return": round(spread - 2 * cost, 6),   # both the long and the short sleeve cross the spread
                   "legs": [{"symbol": l["symbol"], "side": l["side"], "gross_return": l["gross_return"]} for l in settled]}
            self._append_closed(rec, self.CLOSED_LS)
            closed_now.append(rec)

        opened = None
        if not still_open and rth:
            tg = self._signal_targets_ls()
            if tg:
                live = self._live_prices([p["symbol"] for p in tg["long"] + tg["short"]])
                legs = []
                for side, picks in (("BUY", tg["long"]), ("SELL", tg["short"])):
                    for p in picks:
                        sym = str(p["symbol"]).upper()
                        entry = live.get(sym)
                        if entry:
                            legs.append({"symbol": sym, "side": side, "entry_close": round(entry, 4),
                                         "trailing_return": p["trailing_return"]})
                n_long = sum(1 for l in legs if l["side"] == "BUY")
                n_short = sum(1 for l in legs if l["side"] == "SELL")
                if n_long >= 3 and n_short >= 3:      # both sleeves must be real baskets, not one lucky name
                    opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                              "top_k": self.TOP_K, "legs": legs}
                    still_open.append(opened)

        self._save_open(still_open, self.OPEN_LS)
        return {"cohorts_closed": len(closed_now), "cohort_opened": bool(opened), "open_cohorts": len(still_open)}

    # ---- positions + report --------------------------------------------------------------------
    def open_positions(self, path=None):
        cohorts = self._load_open(path)
        prices = self._live_prices([l["symbol"] for co in cohorts for l in co.get("legs", [])])
        rows = []
        for co in cohorts:
            held = self._biz_days_elapsed(co.get("opened"))
            for leg in co.get("legs", []):
                ec = self._f2(leg.get("entry_close")) or 0.0
                cur = prices.get(str(leg["symbol"]).upper())
                side = str(leg.get("side") or "BUY").upper()
                # signed by side: a short profits when price falls, like unrealized_pct
                pct = (round(100 * ((cur / ec - 1.0) if side == "BUY" else (ec / cur - 1.0)), 2)
                       if (cur and ec > 0) else None)
                rows.append({"symbol": leg["symbol"], "side": side, "entry_date": co.get("opened"),
                             "entry_close": round(ec, 4) if ec else None,
                             "live_last": round(cur, 4) if cur else None,
                             "unrealized_pct": pct,
                             "live_dir": (None if pct is None else ("up" if pct > 0 else ("down" if pct < 0 else "flat"))),
                             "trailing_return_pct": round(100 * self._f2(leg.get("trailing_return") or 0), 2),
                             "days_held": held, "days_to_settle": max(0, self.HOLD_DAYS - held)})
        rows.sort(key=lambda r: (r.get("trailing_return_pct") or 0), reverse=True)
        return rows

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    def _series_stats(self, rets):
        """Compact cumulative/mean/Sharpe/win-rate summary for a list of per-cohort net returns."""
        n = len(rets)
        if n == 0:
            return {"n": 0}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        return {"n": n, "cumulative_return_pct": round(100 * (eq - 1), 2),
                "avg_net_return_per_week_bps": round(mean * 10000, 2),
                "annualized_sharpe": round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0,
                "win_rate_pct": round(100 * sum(1 for r in rets if r > 0) / n, 1)}

    def _long_short_report(self):
        """The market-neutral twin's sub-report: its own closed-cohort verdict on the SAME court bar, plus the
        current open spread cohort. This is the pure cross-sectional momentum EDGE (equity beta netted out) —
        judge the strategy on THIS, not the beta-laden long-only basket."""
        from app.services.shadow_contract_sizing import enrich_open_rows
        closed = self._closed(self.CLOSED_LS)
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        positions = enrich_open_rows(self.open_positions(self.OPEN_LS))
        stats = self._series_stats(rets)
        accumulating = len(rets) < self.MIN_COHORTS
        return {
            "track": "LONG/SHORT (market-neutral spread)",
            "signal": f"cross-sectional momentum SPREAD · top-{self.TOP_K} long / bottom-{self.TOP_K} short",
            "cohorts_closed": len(rets), "min_cohorts": self.MIN_COHORTS,
            "open_cohorts": len(self._load_open(self.OPEN_LS)), "open_positions": positions,
            "rigorous_verdict": _rigorous_verdict(rets, self.MIN_COHORTS),
            "stats": stats,
            "cost_note": "both sleeves cross the round-trip spread → cost is 2x the long-only track's per cohort",
            "status": ("ETF_LS_NO_DATA" if not rets else
                       ("ETF_LS_ACCUMULATING" if accumulating else "ETF_LS_MEASURING")),
            "verdict": (f"{len(positions)} open ({sum(1 for p in positions if p['side']=='BUY')} long / "
                        f"{sum(1 for p in positions if p['side']=='SELL')} short) — first spread cohort settles "
                        f"~{self.HOLD_DAYS} business days after opening" if not rets else
                        f"accumulating ({len(rets)}/{self.MIN_COHORTS} weekly spread cohorts) — not enough yet"
                        if accumulating else
                        f"measuring: market-neutral net Sharpe {stats['annualized_sharpe']} over {len(rets)} weeks"),
        }

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self):
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        rigorous = _rigorous_verdict(rets, self.MIN_COHORTS)
        from app.services.shadow_contract_sizing import enrich_open_rows
        positions = enrich_open_rows(self.open_positions())   # + contracts + total-$ P/L (hypothetical lots)
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "ExtendedEtfShadowEngine", "universe_size": len(self._universe()),
                "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS, "rigorous_verdict": rigorous,
                "open_cohorts": len(self._load_open()), "open_positions": positions,
                "signal": f"cross-sectional momentum · {self.LOOKBACK}d trailing · top-{self.TOP_K} long",
                "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
                "long_short": self._long_short_report() if self._ls_enabled() else {"status": "ETF_LS_DISABLED"},
                "note": ("ZERO-capital forward-test of the 52-ETF extended universe: rank by trailing return, "
                         "hold top-K a week, settle at live quotes, judged on the live edge court's bar. The "
                         "long-only track is mostly equity beta; the long_short track is the pure market-neutral "
                         "momentum SPREAD — judge the edge on that. NO orders/budget.")}
        if n == 0:
            return {**base, "status": "ETF_SHADOW_NO_DATA",
                    "verdict": (f"{len(positions)} open — the first weekly cohort settles ~{self.HOLD_DAYS} "
                                "business days after opening" if positions else
                                "no cohorts yet — the first opens next mark on the top-K relative-strength ETFs")}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {**base,
                "status": "ETF_SHADOW_ACCUMULATING" if accumulating else "ETF_SHADOW_MEASURING",
                "cumulative_return_pct": round(100 * (eq - 1), 2),
                "avg_net_return_per_week_bps": round(mean * 10000, 2),
                "annualized_sharpe": sharpe, "win_rate_pct": round(100 * wins / n, 1),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} weekly cohorts) — not enough live history yet"
                            if accumulating else
                            f"measuring: live net Sharpe {sharpe} (annualized), win rate "
                            f"{round(100 * wins / n, 1)}% over {n} weeks")}
