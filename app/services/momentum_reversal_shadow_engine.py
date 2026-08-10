"""Momentum-reversal EQUITY SHADOW forward-test — measures the true factor edge with ZERO capital.

Why this exists: the momentum-reversal sleeve's OPTIONS form is a documented NO-GO (an OTM round-trip
costs 500-1500bps, 10-30x the ~0.23%/5d edge). The EQUITY form is the only version that could survive,
but its backtested magnitude is SURVIVORSHIP-BIASED (the CSV universe is today's winners) and its net-of-
cost Sharpe is thin (backtest OOS ~0.42 gross -> ~0.08 @10bps round-trip). The MomentumReversalStrategy-
Engine's own docstring says it "exists to trade it FORWARD on real data... and let the fixed-horizon
grader measure the true edge." This tracker IS that grader — it runs the exact strategy on real forward
settled bars (NO orders, NO budget) so we learn whether the factor survives live BEFORE committing capital.

Method mirrors MomentumReversalBacktestEngine EXACTLY so the live number is directly comparable to the
backtest: reuse the real `select()` signal (12-1 momentum AND 5-day reversal must agree), open a NON-
OVERLAPPING weekly cohort of the top-N confirmed names as EQUITY, hold HOLD_DAYS=5 trading days, book the
per-name forward return (long = fwd/entry-1, short = the negative), net the round-trip cost, and average
the legs into one period ("cohort") return — the diversified basket the thin edge only survives inside.

Driven by SETTLED daily bars (a leg closes the moment its own CSV advances HOLD_DAYS past entry — robust
to when the scheduler fires), no broker calls, self-gated. Accumulates forward from first run (no
backfill), so it carries no survivorship bias. Verdict language mirrors EdgePersistence (the court).
"""

import csv
import glob
import json
import math
import os
import time
from datetime import datetime
from os import getenv
from pathlib import Path


class MomentumReversalShadowEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/momentum_reversal")
    OPEN = STATE / "shadow_open_cohorts.json"       # cohorts with legs still within their hold window
    CLOSED = STATE / "shadow_closed_cohorts.jsonl"  # realized period returns (one line per closed cohort)
    BENCH_CACHE = STATE / "top_candidates_cache.json"  # the board reads this; refreshed here when stale
    BENCH_N = 30                  # depth of the "next up" bench written for the Opportunity Board
    BENCH_TTL_SECONDS = 900       # only refresh the board cache when it's older than this (15 min)

    HOLD_DAYS = 5                 # non-overlapping weekly hold — matches the reversal horizon + backtest
    MIN_COHORTS = 8               # ~2 months of weekly periods before the Sharpe verdict is trustworthy
    PERIODS_PER_YEAR = 252 / 5    # 50.4, the backtest's annualization

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

    # ---- data ----------------------------------------------------------------------------------

    def _closes(self, sym):
        """Full settled closes (oldest->newest) for a symbol, or [] — same parse as the strategy feed
        so a stored entry index stays aligned across reloads (CSVs are append-only)."""
        out = []
        try:
            with open(self.HIST / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    try:
                        c = float(r["close"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if c > 0:
                        out.append(c)
        except Exception:
            return []
        return out

    def _signal_targets(self):
        """The real live signal on SETTLED bars: (top_n targets, full clean bench, as_of, top_n). Reuses the
        strategy engine's own CSV universe (MIN_BARS + pre-listing exclusions) and pure select() — no
        reimplementation, no fetch."""
        from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
        eng = MomentumReversalStrategyEngine()
        series, asof, _src = eng.universe(prefer_live=False)   # settled CSVs only — deterministic, no network
        if not series:
            return [], [], None, eng.top_n
        _top, confirmed = eng.select(series)
        # Apply the SAME trash-pick failsafe the live sleeve uses (penny/warrant/artifact-momentum/crash),
        # then take the top_n — so the shadow measures what the live EQUITY sleeve would ACTUALLY trade,
        # not the factor on junk names it would never touch. Fails open (no filter -> use raw ranking).
        try:
            from app.services.trash_pick_filter_engine import TrashPickFilterEngine
            clean, _discarded = TrashPickFilterEngine.partition(confirmed)
        except Exception:
            clean = confirmed
        targets = clean[:eng.top_n]
        # annotate each target with its entry index in its OWN series (len-1 = latest settled bar)
        for t in targets:
            t["_entry_idx"] = len(series.get(t["symbol"], [])) - 1
        return targets, clean, asof, eng.top_n

    def _refresh_bench_cache(self, clean, asof):
        """Keep the Opportunity Board's momentum candidates CURRENT. The board reads top_candidates_cache.json,
        which only the heavy live /top-candidates scan refreshes — so while the sleeve is parked it goes stale
        (was 9 days old). The shadow already computed the fresh signal this cycle, so write the bench here (in
        the exact schema _compute uses) — but only when the cache is stale, so a fresh LIVE compute is never
        clobbered by settled-bar data."""
        try:
            if self.BENCH_CACHE.exists():
                age = time.time() - float(json.loads(self.BENCH_CACHE.read_text()).get("computed_epoch") or 0)
                if age < self.BENCH_TTL_SECONDS:
                    return False
        except Exception:
            pass
        candidates = []
        for i, t in enumerate(clean[:self.BENCH_N], start=1):
            candidates.append({
                "rank": i, "symbol": t.get("symbol"), "side": t.get("side"),
                "direction": "LONG" if t.get("side") == "BUY" else "SHORT",
                "directional_bias": t.get("directional_bias"),
                "conviction": t.get("conviction"),
                "momentum_rank": t.get("momentum_rank"), "reversal_rank": t.get("reversal_rank"),
                "momentum_12_1_pct": round(float(t.get("momentum_12_1_pct") or 0), 1),
                "reversal_5d_move_pct": round(float(t.get("reversal_5d_move_pct") or 0), 1),
                "last_close": t.get("last_close"),
            })
        payload = {
            "computed_at": datetime.utcnow().isoformat(), "computed_epoch": time.time(),
            "as_of": asof, "data_source": "TRADESTATION_SETTLED_SHADOW",
            "confirmed_signals": len(clean), "clean_signals": len(clean),
            "candidates": candidates, "trash_discarded": 0, "trash_discarded_names": [],
            "contract_board": {"top_scoring_contract": None, "affordable_contracts": [],
                               "status": "SHADOW_REFRESH_NO_CONTRACTS",
                               "detail": "bench refreshed by the equity shadow (settled bars); option "
                                         "contracts are scored only by the live /top-candidates scan"},
            "engine": "MomentumReversalShadowEngine",
            "signal": "12-1 momentum AND 5-day reversal must agree; conviction = percentile-rank blend",
            "status": "TOP_CANDIDATES_READY",
        }
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.BENCH_CACHE.write_text(json.dumps(payload))
            return True
        except Exception:
            return False

    def open_symbols(self):
        """Symbols in the currently-open shadow cohort (for the board to exclude — they're 'held' by the
        shadow and shown on the open-positions card, so the board stays a genuine 'not executed' bench)."""
        out = set()
        for co in self._load_open():
            for leg in co.get("legs", []):
                out.add(str(leg.get("symbol") or "").upper())
        return out

    def open_positions(self):
        """The open shadow cohort as 'positions': entry, current settled price, unrealized shadow P&L, and
        days-to-settle. Zero-capital — these are hypothetical holdings the forward-test is marking."""
        rows = []
        for co in self._load_open():
            for leg in co.get("legs", []):
                closes = self._closes(leg["symbol"])
                ei = int(leg["entry_idx"])
                ec = float(leg.get("entry_close") or 0)
                cur = closes[-1] if closes else None
                bars_elapsed = (len(closes) - 1 - ei) if closes else 0
                unreal = None
                if cur and ec > 0:
                    unreal = (cur / ec - 1.0) if leg["side"] == "BUY" else (ec / cur - 1.0)
                rows.append({
                    "symbol": leg["symbol"], "side": leg["side"],
                    "entry_date": co.get("opened"), "entry_close": round(ec, 4) if ec else None,
                    "current_close": round(cur, 4) if cur else None,
                    "unrealized_pct": round(100 * unreal, 2) if unreal is not None else None,
                    "days_held": max(0, bars_elapsed),
                    "days_to_settle": max(0, self.HOLD_DAYS - bars_elapsed),
                    "conviction": leg.get("conviction"),
                })
        rows.sort(key=lambda r: (r.get("conviction") or 0), reverse=True)
        return rows

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

    # ---- mark ----------------------------------------------------------------------------------

    def mark(self):
        """Advance the shadow: close any legs that have completed their HOLD_DAYS window, then (weekly,
        non-overlapping) open a fresh cohort from the current signal. Books realized period returns."""
        if not self.enabled():
            return {"status": "MOM_SHADOW_DISABLED", "acted": False}

        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        # 1) settle matured legs — a leg exits when its own series advanced >= HOLD_DAYS bars past entry
        for co in cohorts:
            legs, matured = co.get("legs", []), []
            unresolved = []
            for leg in legs:
                closes = self._closes(leg["symbol"])
                ei = int(leg["entry_idx"])
                if len(closes) > ei + self.HOLD_DAYS:
                    exit_close = closes[ei + self.HOLD_DAYS]
                    ec = float(leg["entry_close"])
                    if ec > 0:
                        gross = (exit_close / ec - 1.0) if leg["side"] == "BUY" else (ec / exit_close - 1.0)
                        matured.append({**leg, "exit_close": round(exit_close, 4),
                                        "gross_return": round(gross, 6)})
                    # a zero/negative entry price is unusable — drop the leg (never fabricate a return)
                else:
                    unresolved.append(leg)

            # a cohort settles as ONE period only when ALL its legs have matured (non-overlapping backtest
            # method: the whole basket rolls at HOLD_DAYS). Until then it stays open.
            if unresolved:
                still_open.append({**co, "legs": unresolved,
                                   "settled_legs": co.get("settled_legs", []) + matured})
                continue
            settled = co.get("settled_legs", []) + matured
            if settled:
                gross_mean = sum(l["gross_return"] for l in settled) / len(settled)
                net_mean = gross_mean - cost
                rec = {
                    "opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                    "n_legs": len(settled), "cost_roundtrip_bps": round(cost * 10000, 2),
                    "gross_return": round(gross_mean, 6), "net_return": round(net_mean, 6),
                    "legs": [{"symbol": l["symbol"], "side": l["side"],
                              "gross_return": l["gross_return"]} for l in settled],
                }
                self._append_closed(rec)
                closed_now.append(rec)

        # 2) open a fresh NON-OVERLAPPING cohort — only if nothing is currently open (the prior basket has
        #    fully rolled). This spaces cohorts >= HOLD_DAYS apart exactly like the backtest's rebal points.
        opened = None
        targets, clean_bench, asof, top_n = self._signal_targets()
        self._refresh_bench_cache(clean_bench, asof)          # keep the Opportunity Board current (write-if-stale)
        if not still_open:
            picks = [t for t in targets if t.get("_entry_idx", -1) >= 0 and t.get("last_close", 0) > 0]
            if picks:
                opened = {
                    "opened": asof, "opened_at": datetime.utcnow().isoformat(), "top_n": top_n,
                    "legs": [{"symbol": t["symbol"], "side": t["side"],
                              "entry_close": round(t["last_close"], 4), "entry_idx": t["_entry_idx"],
                              "conviction": t.get("conviction")} for t in picks],
                    "settled_legs": [],
                }
                still_open.append(opened)

        self._save_open(still_open)
        return {"status": "MOM_SHADOW_MARKED", "acted": bool(closed_now or opened),
                "cohorts_closed": len(closed_now), "cohort_opened": bool(opened),
                "open_cohorts": len(still_open)}

    # ---- report --------------------------------------------------------------------------------

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
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "MomentumReversalShadowEngine",
            "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
            "open_cohorts": len(open_cohorts),
            "open_positions": positions,
            "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
            "backtest_reference": {"oos_sharpe_gross": 0.42, "oos_sharpe_net_10bps": 0.08,
                                   "caveat": "backtest magnitude is survivorship-biased (CSV = today's "
                                             "winners); THIS forward number is not"},
            "note": ("SHADOW forward-test of the EQUITY momentum-reversal factor — hypothetical weekly "
                     "long/short basket P&L, NO orders, NO budget. Accumulates forward from first run."),
        }
        if n == 0:
            return {**base, "status": "MOM_SHADOW_NO_DATA",
                    "verdict": "no closed cohorts yet — first period settles ~1 week after the first mark"}

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
