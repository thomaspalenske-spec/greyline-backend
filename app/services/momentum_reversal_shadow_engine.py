"""Momentum-reversal EQUITY SHADOW forward-test — measures the true factor edge with ZERO capital.

Why this exists: the momentum-reversal sleeve's OPTIONS form is a documented NO-GO (an OTM round-trip
costs 500-1500bps, 10-30x the ~0.23%/5d edge). The EQUITY form is the only version that could survive,
but its backtested magnitude is SURVIVORSHIP-BIASED (the CSV universe is today's winners) and its net-of-
cost Sharpe is thin (backtest OOS ~0.42 gross -> ~0.08 @10bps round-trip). The MomentumReversalStrategy-
Engine's own docstring says it "exists to trade it FORWARD on real data... and let the fixed-horizon
grader measure the true edge." This tracker IS that grader — runs the exact strategy forward (NO orders,
NO budget) so we learn whether the factor survives live BEFORE committing capital.

DATA BASIS (revised 2026-08-10): LIVE prices, time-based settlement. The broad equity universe's CSVs are
NOT refreshed daily (only decision symbols are), so a settled-bar shadow opened on WEEKS-old closes and its
legs could never settle. So instead: SELECT + ENTER on the live universe (prefer_live — matches production
/top-candidates; if it falls back to stale CSV we DON'T open), then hold a NON-OVERLAPPING weekly cohort of
the top-N and SETTLE after HOLD_DAYS business days at the live quote — long = exit/entry-1, short = the
inverse, leg-mean per cohort, net the round-trip cost. Accumulates forward from first run (no survivorship
bias). Verdict language mirrors EdgePersistence (the court).
"""

import json
import math
import time
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path


class MomentumReversalShadowEngine:

    STATE = Path("app/data/momentum_reversal")
    OPEN = STATE / "shadow_open_cohorts.json"       # the one open weekly cohort (until it settles)
    CLOSED = STATE / "shadow_closed_cohorts.jsonl"  # realized period returns (one line per closed cohort)
    BENCH_CACHE = STATE / "top_candidates_cache.json"  # the LIVE momentum scan (production /top-candidates writes it)
    TOP_N = 10                    # weekly basket size (matches the live strategy's top_n)
    SCAN_MAX_AGE_SECONDS = 26 * 3600   # only open on a scan this fresh (allows a once-daily warm)

    HOLD_DAYS = 5                 # non-overlapping weekly hold, in BUSINESS days — matches the backtest
    MIN_COHORTS = 8               # ~2 months of weekly periods before the Sharpe verdict is trustworthy
    PERIODS_PER_YEAR = 252 / 5    # 50.4, the backtest's annualization

    LIVE_SOURCES = ("TRADESTATION_LIVE", "TRADESTATION_LIVE_CACHED")

    @staticmethod
    def enabled():
        # default TRUE — the whole point is to accumulate live evidence while the sleeve is parked.
        # It NEVER places an order (measurement only), so "on" costs nothing and commits no budget.
        return (getenv("GREYLINE_MOMENTUM_EQUITY_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _cost_roundtrip():
        # ONE cost source: reuse the strategy engine's own round-trip knob so the shadow and the live
        # sleeve are judged on the identical friction assumption (default 10bps).
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

    # ---- time + live prices --------------------------------------------------------------------

    @staticmethod
    def _today():
        return datetime.utcnow().date()

    @classmethod
    def _biz_days_elapsed(cls, start_iso):
        """Business days from an entry date (exclusive) to today (inclusive). 5 == a weekly hold done."""
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
            if d.weekday() < 5:          # Mon-Fri
                n += 1
        return n

    def _live_prices(self, syms):
        """{SYM: last_price} from the batched TradeStation quote engine (one request, 60s TTL cache).
        Fails soft to {} — the caller never fabricates a price."""
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

    # ---- signal --------------------------------------------------------------------------------

    def _signal_targets(self, prefer_live=True):
        """Source the weekly picks from the LIVE momentum scan cache (top_candidates_cache.json — production
        /top-candidates writes it on a real ~2000-name universe fetch). Returns (top_n picks, full bench,
        as_of, top_n, source). The shadow NEVER triggers that heavy fetch itself (it would hammer TS); it
        opens ONLY on a scan that is BOTH fresh (<=SCAN_MAX_AGE) and live-sourced — otherwise `source` comes
        back as STALE_SCAN / NO_SCAN so mark() refuses to open (never enters on stale data — the whole bug)."""
        try:
            d = json.loads(self.BENCH_CACHE.read_text())
        except Exception:
            return [], [], None, self.TOP_N, "NO_SCAN"
        src = d.get("data_source")
        as_of = d.get("as_of")
        epoch = self._f2(d.get("computed_epoch")) or 0.0
        fresh = (time.time() - epoch) <= self.SCAN_MAX_AGE_SECONDS
        cands = d.get("candidates") or []
        bench = [{"symbol": c.get("symbol"), "side": c.get("side"),
                  "last_close": c.get("last_close"), "conviction": c.get("conviction")} for c in cands]
        picks = [c for c in bench if self._f2(c.get("last_close"))][:self.TOP_N]
        eff_source = src if (fresh and src in self.LIVE_SOURCES) else "STALE_SCAN"
        return picks, bench, as_of, self.TOP_N, eff_source

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

    def _append_closed(self, cohort):
        self.STATE.mkdir(parents=True, exist_ok=True)
        with open(self.CLOSED, "a") as f:
            f.write(json.dumps(cohort) + "\n")

    def _closed(self):
        out = []
        try:
            for ln in self.CLOSED.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    def open_symbols(self):
        """Symbols in the currently-open shadow cohort (for the board to exclude — they're 'held' by the
        shadow and shown on the open-positions card, so the board stays a genuine 'not executed' bench)."""
        out = set()
        for co in self._load_open():
            for leg in co.get("legs", []):
                out.add(str(leg.get("symbol") or "").upper())
        return out

    # ---- mark ----------------------------------------------------------------------------------

    def mark(self):
        """Settle any cohort that has completed its HOLD_DAYS business-day hold (at live quotes), then
        (weekly, non-overlapping) open a fresh cohort from the LIVE signal. NO orders, NO budget."""
        if not self.enabled():
            return {"status": "MOM_SHADOW_DISABLED", "acted": False}

        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        # 1) settle matured cohorts — the whole basket rolls together at HOLD_DAYS business days
        for co in cohorts:
            legs = co.get("legs", [])
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            prices = self._live_prices([l["symbol"] for l in legs])
            settled = []
            for leg in legs:
                px = prices.get(str(leg["symbol"]).upper())
                ec = self._f2(leg.get("entry_close"))
                if px and ec and ec > 0:
                    gross = (px / ec - 1.0) if leg["side"] == "BUY" else (ec / px - 1.0)
                    settled.append({**leg, "exit_close": round(px, 4), "gross_return": round(gross, 6)})
            if len(settled) < len(legs):
                # couldn't price every leg this cycle (quote gap) — retry next mark rather than book a
                # partial, distorted basket. The hold is already satisfied; it settles when quotes return.
                still_open.append(co)
                continue
            gross_mean = sum(l["gross_return"] for l in settled) / len(settled)
            rec = {
                "opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                "n_legs": len(settled), "cost_roundtrip_bps": round(cost * 10000, 2),
                "gross_return": round(gross_mean, 6), "net_return": round(gross_mean - cost, 6),
                "legs": [{"symbol": l["symbol"], "side": l["side"], "gross_return": l["gross_return"]}
                         for l in settled],
            }
            self._append_closed(rec)
            closed_now.append(rec)

        # 2) open a fresh NON-OVERLAPPING cohort on the LIVE signal — only when nothing is open, and only
        #    on a REAL live feed (never on a stale CSV fallback: that was the whole bug).
        opened, skip_reason = None, None
        targets, clean_bench, asof, top_n, source = self._signal_targets(prefer_live=True)
        if not still_open:
            if source not in self.LIVE_SOURCES:
                skip_reason = ("waiting for a fresh LIVE momentum scan — NOT opening on stale/absent data "
                               f"(scan source={source!r}). The scan is produced by /top-candidates on a live "
                               "universe fetch; the shadow won't trigger that heavy ~2000-name fetch itself.")
            else:
                picks = [t for t in targets if self._f2(t.get("last_close")) and self._f2(t.get("last_close")) > 0]
                if picks:
                    opened = {
                        "opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                        "top_n": top_n, "source": source,
                        "legs": [{"symbol": t["symbol"], "side": t["side"],
                                  "entry_close": round(float(t["last_close"]), 4),
                                  "conviction": t.get("conviction")} for t in picks],
                    }
                    still_open.append(opened)

        self._save_open(still_open)
        out = {"status": "MOM_SHADOW_MARKED", "acted": bool(closed_now or opened),
               "cohorts_closed": len(closed_now), "cohort_opened": bool(opened),
               "open_cohorts": len(still_open), "universe_source": source}
        if skip_reason:
            out["open_skipped"] = skip_reason
        return out

    # ---- positions + report --------------------------------------------------------------------

    def open_positions(self):
        """The open shadow cohort as 'positions', marked at LIVE quotes: entry, live price, unrealized
        shadow P&L (signed by side), and business-days-to-settle. Zero-capital, hypothetical holdings."""
        cohorts = self._load_open()
        syms = [l["symbol"] for co in cohorts for l in co.get("legs", [])]
        prices = self._live_prices(syms)
        rows = []
        for co in cohorts:
            held = self._biz_days_elapsed(co.get("opened"))
            for leg in co.get("legs", []):
                ec = self._f2(leg.get("entry_close")) or 0.0
                cur = prices.get(str(leg["symbol"]).upper())
                unreal = None
                if cur and ec > 0:
                    unreal = (cur / ec - 1.0) if leg["side"] == "BUY" else (ec / cur - 1.0)
                pct = round(100 * unreal, 2) if unreal is not None else None
                rows.append({
                    "symbol": leg["symbol"], "side": leg["side"],
                    "entry_date": co.get("opened"), "entry_close": round(ec, 4) if ec else None,
                    "current_close": round(cur, 4) if cur else None,
                    "live_last": round(cur, 4) if cur else None,
                    "unrealized_pct": pct, "live_pct": pct,
                    "live_dir": (None if pct is None else ("up" if pct > 0 else ("down" if pct < 0 else "flat"))),
                    "days_held": held, "days_to_settle": max(0, self.HOLD_DAYS - held),
                    "conviction": leg.get("conviction"),
                })
        rows.sort(key=lambda r: (r.get("conviction") or 0), reverse=True)
        return rows

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    def report(self):
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        open_cohorts = self._load_open()
        positions = self.open_positions()
        entry_source = (open_cohorts[0].get("source") if open_cohorts else None)
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "MomentumReversalShadowEngine",
            "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
            "open_cohorts": len(open_cohorts),
            "open_positions": positions,
            "entry_source": entry_source,
            "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
            "backtest_reference": {"oos_sharpe_gross": 0.42, "oos_sharpe_net_10bps": 0.08,
                                   "caveat": "backtest magnitude is survivorship-biased (CSV = today's "
                                             "winners); THIS forward number is not"},
            "note": ("SHADOW forward-test of the EQUITY momentum-reversal factor — hypothetical weekly "
                     "long/short basket, LIVE entry + live settlement after 5 business days, NO orders/budget."),
        }
        if n == 0:
            return {**base, "status": "MOM_SHADOW_NO_DATA",
                    "verdict": ("no closed cohorts yet — the first weekly cohort settles ~5 business days "
                                "after it opens on a live signal")}

        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {
            **base,
            "status": "MOM_SHADOW_ACCUMULATING" if accumulating else "MOM_SHADOW_MEASURING",
            "cumulative_return_pct": round(100 * (eq - 1), 2),
            "avg_net_return_per_week_bps": round(mean * 10000, 2),
            "annualized_sharpe": sharpe,
            "win_rate_pct": round(100 * wins / n, 1),
            "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} weekly cohorts) — not enough live history "
                        f"to trust yet"
                        if accumulating else
                        f"measuring: live net Sharpe {sharpe} (annualized) vs backtest {base['backtest_reference']['oos_sharpe_net_10bps']} "
                        f"net@10bps; win rate {round(100 * wins / n, 1)}% over {n} weeks — this is the "
                        f"UN-biased forward read the backtest couldn't give"),
        }
