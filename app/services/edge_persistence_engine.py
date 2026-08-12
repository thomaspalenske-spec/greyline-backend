"""Live per-sleeve edge court — the discipline GreyLine lacked: measure whether each strategy is
ACTUALLY earning, cost-net and with statistical honesty, so decayed sleeves are retired on evidence
and a real edge can be PROVEN instead of asserted.

Medallion's core discipline isn't a magic signal — it's relentlessly retiring signals as they decay,
which requires knowing, per strategy, whether it still works. This engine is that court.

TWO layers, and only ONE is evidence:
  * realized_edge()  — AUTHORITATIVE. Per-trade return on risk from CLOSED trades (forced flattens
    excluded), cost-net, with N / win-rate / t-stat / 95% CI and a minimum-sample gate. Verdict:
    PROVEN / DECAYED / UNPROVEN / ACCUMULATING. This is the number that moves the Edge grade.
  * open_drift  — CONTEXT ONLY. Daily marks of OPEN-position unrealized P&L. These are autocorrelated
    (100 daily marks of one held trade ≈ 1 sample, not 100), so "positive most days" is NOT evidence
    of edge — the exact false-confidence trap this system has been bitten by. Never used for a verdict.

Attribution is by instrument (the sleeves trade distinct things):
  carry -> SVXY | trend -> ETF basket | tbill -> SGOV | premium -> options (VRP + earnings) |
  momentum -> any other equity. Read-only; it never trades.
"""

import json
import math
from datetime import datetime
from pathlib import Path


class EdgePersistenceEngine:

    DIR = Path("app/data/edge_persistence")
    LEDGER = DIR / "daily_marks.jsonl"
    VRP_LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
    OPT_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
    EQ_LEDGER = Path("app/data/paper_trading/paper_trade_ledger.jsonl")
    # Direct-to-broker ETF sleeves (trend/carry/MF/low-vol) record their FIFO closes here with an EXPLICIT
    # sleeve tag — previously invisible to the court. See SleeveTradeLedgerEngine.
    SLEEVE_LEDGER = Path("app/data/paper_trading/sleeve_trade_ledger.jsonl")

    CARRY = {"SVXY"}
    TREND = {"QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"}
    TBILL = {"SGOV"}
    MIN_DAYS = 10                       # open-drift context needs this much history to even show
    MIN_TRADES = 20                     # below this, NO realized verdict — too few samples to judge
    Z95 = 1.96                          # 2-sided 95% normal quantile (base for the small-sample t bump)
    MIN_EDGE_ROR = 0.005                # PROVEN also needs a mean edge >= 0.5% return-on-risk/trade — a
                                        # statistically-significant-but-trivial edge must not fire capital moves
    # INSTRUMENT-AWARE RISK BASIS — return-on-risk must divide by comparable "intended max loss" per sleeve:
    #   condor -> defined max_loss (exact) | long option -> premium paid (= max loss) | equity -> stop-loss.
    # Equity stops aren't recorded in the ledger, so use a volatility proxy: the momentum doctrine stop is
    # ~2.5 ATR, typically ~8-20% of price -> 12% central. Makes momentum's ROR comparable to a condor's.
    EQUITY_STOP_PCT = 0.12

    @classmethod
    def _t_crit(cls, n):
        """Two-sided 95% critical value, SMALL-SAMPLE AWARE. The flat 1.96 normal is anti-conservative at
        N~20 (Student-t needs ~2.09), so a thin-but-lucky sample could clear a 1.96 CI and trip the whole
        act-on-it machinery. Cornish-Fisher expansion of z=1.96 → t (df=n-1): converges to 1.96 for large
        N, appropriately wider for small N (df=19 → ~2.09, matching the t-table)."""
        df = max(1, int(n) - 1)
        z = cls.Z95
        return z + (z ** 3 + z) / (4.0 * df)

    @classmethod
    def verdict_from_returns(cls, returns, min_n=None, min_edge=0.0):
        """The court's RIGOROUS verdict, reusable on ANY cost-net return series — so a zero-capital SHADOW
        is judged on the SAME bar as a live sleeve (small-sample-t 95% CI, cost-net, min-N gate), not a
        softer raw-Sharpe/win-rate summary that could lure a re-arm on a not-actually-significant edge.

        returns: cost-net per-observation returns (fractions). min_n: samples required before any verdict
        (defaults to MIN_TRADES). min_edge: optional action floor on the mean (0 = pure significance).
        Returns n / mean / CI / t-stat / significance and a PROVEN|DECAYED|UNPROVEN|ACCUMULATING verdict."""
        import math
        min_n = cls.MIN_TRADES if min_n is None else int(min_n)
        rets = [cls._f(r) for r in returns if r is not None]
        n = len(rets)
        if n == 0:
            return {"n": 0, "verdict": f"ACCUMULATING (0/{min_n} — no closed observations yet)",
                    "significant": False, "min_n": min_n}
        mean = sum(rets) / n
        out = {"n": n, "min_n": min_n, "mean_pct": round(mean * 100, 4)}
        if n < 2:
            out.update({"verdict": f"ACCUMULATING ({n}/{min_n} — too few to judge)", "significant": False})
            return out
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        sd = math.sqrt(var)
        se = sd / math.sqrt(n) if n else 0.0
        t_stat = mean / se if se > 0 else 0.0
        tc = cls._t_crit(n)
        lo, hi = mean - tc * se, mean + tc * se
        out.update({"std_pct": round(sd * 100, 4), "t_stat": round(t_stat, 2), "t_crit": round(tc, 3),
                    "ci95_pct": [round(lo * 100, 4), round(hi * 100, 4)],
                    "significant": bool(lo > 0 or hi < 0)})
        if n < min_n:
            out["verdict"] = f"ACCUMULATING ({n}/{min_n} — too few to judge)"
        elif lo > 0 and mean >= min_edge:
            out["verdict"] = ("PROVEN — cost-net edge > 0 at 95% (small-sample t)"
                              + (f" and ≥ {round(min_edge * 100, 2)}% floor" if min_edge > 0 else ""))
        elif hi < 0:
            out["verdict"] = "DECAYED — cost-net edge < 0 at 95% (small-sample t); retire"
        elif lo > 0:
            out["verdict"] = (f"UNPROVEN — statistically positive but mean {round(mean * 100, 3)}% "
                              f"< {round(min_edge * 100, 2)}% action floor")
        else:
            out["verdict"] = "UNPROVEN — edge indistinguishable from zero net of cost"
        return out
    CONDOR_CLOSE_HAIRCUT_FRAC = 0.03    # condor closes are marked at MID; haircut this frac of max-loss
                                        # as a conservative round-trip close-spread proxy (see cost_note)
    # forced/administrative closes are NOT strategy outcomes — exclude from the edge stats
    FORCED_MARKERS = ("clean_slate", "flatten", "rebaseline", "reset", "mechanics test",
                      "liquidat", "manual")

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _sleeve_of(cls, symbol, asset_type):
        sym = str(symbol or "").upper()
        if str(asset_type or "").upper() in ("STOCKOPTION", "OPTION"):
            return "premium"
        base = sym.split()[0] if sym else sym
        if base in cls.CARRY:
            return "carry"
        if base in cls.TREND:
            return "trend"
        if base in cls.TBILL:
            return "tbill"
        return "momentum"

    @classmethod
    def _forced(cls, reason):
        r = str(reason or "").lower()
        return any(m in r for m in cls.FORCED_MARKERS)

    @staticmethod
    def _read(path):
        try:
            return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
        except Exception:
            return []

    # ---------------------------------------------------------------- realized edge (AUTHORITATIVE)

    def _closed_trades(self):
        """Realized CLOSED trades per sleeve, forced flattens excluded. Returns (trades, excluded_count).
        Each trade: {sleeve, gross, net, risk, closed_at, basis}. `net` is cost-net; `risk` is the
        capital-at-risk basis the return is measured against (condor max-loss; equity/option notional)."""
        trades, excluded = [], 0

        # VRP + earnings condors: defined-risk (basis = max_loss_total); realized_pnl is a MID estimate
        # at the close decision, so haircut a conservative round-trip close spread to avoid over-claiming.
        for r in self._read(self.VRP_LEDGER):
            if str(r.get("status")).upper() != "CLOSED":
                continue
            if self._forced(r.get("close_reason")):
                excluded += 1
                continue
            rp, risk = r.get("realized_pnl"), self._f(r.get("max_loss_total"))
            if rp is None or risk <= 0:
                continue
            # Closes priced from actual fills or the marketable close-order debit are already honest —
            # no haircut. Only legacy rows marked at MID (basis 'mid'/absent) get the conservative haircut.
            basis = str(r.get("realized_pnl_basis") or "mid").lower()
            if basis in ("fills", "close_order"):
                net, tag = self._f(rp), basis
            else:
                net, tag = self._f(rp) - self.CONDOR_CLOSE_HAIRCUT_FRAC * risk, "mid_estimate"
            # earnings-vol (event-driven IV crush) and VRP (unconditional variance premium) are DISTINCT
            # edges sharing this ledger — verdict them separately so one can't mask the other.
            strat = str(r.get("strategy") or "vrp").lower()
            sleeve = "premium_earnings" if strat == "earnings_vol" else "premium_vrp"
            trades.append({"sleeve": sleeve, "gross": self._f(rp), "net": net,
                           "risk": risk, "closed_at": r.get("closed_at"), "basis": tag,
                           "risk_kind": "defined_max_loss"})

        # equity + option contracts booked to the SIM: realized_pnl reflects REAL fills (spread already
        # paid) and the SIM charges no commission, so it is already cost-net (basis = entry notional).
        for r in self._read(self.EQ_LEDGER) + self._read(self.OPT_LEDGER):
            if str(r.get("status")).upper() != "CLOSED":
                continue
            if self._forced(r.get("close_reason")):
                excluded += 1
                continue
            rp = r.get("realized_pnl")
            if rp is None:
                continue
            sleeve = self._sleeve_of(r.get("symbol"), r.get("asset_type"))
            is_opt = str(r.get("asset_type") or "").upper() in ("STOCKOPTION", "OPTION")
            mult = 100 if is_opt else 1
            qty = self._f(r.get("original_quantity")) or self._f(r.get("quantity"))
            notional = abs(self._f(r.get("entry_price")) * mult * qty)
            if notional <= 0:
                continue
            # INSTRUMENT-AWARE risk: a long option's premium IS its max loss; an equity's is the intended
            # stop-loss (no stop stored -> vol proxy), so its return-on-risk is comparable to a condor's.
            if is_opt:
                risk, risk_kind = notional, "premium_at_risk"
            else:
                entry, stop_v = self._f(r.get("entry_price")), self._f(r.get("entry_stop"))
                # EXACT only when the stamped stop is a SANE protective distance: positive, on the correct
                # side (below entry for the long dip-buys this sleeve trades), and not a garbage value that
                # would imply >100% risk. Anything else falls back to the vol proxy rather than mislabeling.
                per_share = (entry - stop_v) if (r.get("entry_stop") is not None and entry > 0) else 0.0
                if 0 < per_share < entry:             # EXACT: the doctrine's recorded initial stop distance
                    risk, risk_kind = per_share * abs(qty), "stop_atr_doctrine"
                else:                                 # fallback: vol proxy when no/garbage stop was recorded
                    risk, risk_kind = self.EQUITY_STOP_PCT * notional, f"stop_proxy_{int(self.EQUITY_STOP_PCT*100)}pct"
            # HONEST basis: read what the close reconciler stamped — 'fills' (upgraded to the actual exit
            # fills) or 'quote_estimate' (booked at the decision quote, not yet fill-confirmed). Options
            # book real SIM fills and carry no tag → 'fill_net'. Never hardcode fill-truth we don't have.
            tag = str(r.get("realized_pnl_basis") or "fill_net")
            trades.append({"sleeve": sleeve, "gross": self._f(rp), "net": self._f(rp),
                           "risk": risk, "closed_at": r.get("closed_at"), "basis": tag,
                           "risk_kind": risk_kind})

        # Direct-to-broker ETF sleeves (trend/carry/MF/low-vol): FIFO closes recorded by
        # SleeveTradeLedgerEngine, tagged with an EXPLICIT `sleeve` (no _sleeve_of guess). Quantity is
        # broker-confirmed; realized_pnl is fill-quote net (SIM charges no commission). No protective
        # stop on these rebalance sleeves, so risk = the same vol proxy the equity path falls back to.
        for r in self._read(self.SLEEVE_LEDGER):
            if r.get("kind") != "close" or str(r.get("status")).upper() != "CLOSED":
                continue
            if self._forced(r.get("close_reason")):
                excluded += 1
                continue
            rp, sleeve = r.get("realized_pnl"), str(r.get("sleeve") or "").strip()
            if rp is None or not sleeve:
                continue
            qty = self._f(r.get("quantity"))
            notional = abs(self._f(r.get("entry_price")) * qty)
            if notional <= 0:
                continue
            risk = self.EQUITY_STOP_PCT * notional
            # This ledger holds ONLY direct-to-broker sleeve closes, every one recorded on a CONFIRMED
            # broker-quantity drop (reconcile), mark-priced at that instant. So its exits are 'mark_at_confirm'
            # by construction — legacy rows tagged 'quote_estimate' are the same thing under the old name;
            # read-map them so the court counts them at the hybrid confirmation floor (not as loose estimates).
            _b = str(r.get("realized_pnl_basis") or "mark_at_confirm")
            if _b == "quote_estimate":
                _b = "mark_at_confirm"
            trades.append({"sleeve": sleeve, "gross": self._f(rp), "net": self._f(rp),
                           "risk": risk, "closed_at": r.get("closed_at"),
                           "basis": _b,
                           "risk_kind": f"stop_proxy_{int(self.EQUITY_STOP_PCT * 100)}pct"})
        return trades, excluded

    # court sleeve -> ExecutionLog strategy key (the direct-to-broker equity sleeves are instrumented, each
    # under its own tag — verified in cross_sectional_momentum / low_vol / trend / carry / MF / tbill)
    _EXEC_STRATEGY = {"carry": "carry", "trend": "trend", "tbill": "tbill", "managed_futures": "managed_futures",
                      "xs_momentum": "xs_momentum", "low_vol": "low_vol",
                      "premium_vrp": "premium_vrp", "premium_earnings": "premium_earnings"}
    _COURT_SLEEVES = ("momentum", "carry", "trend", "tbill", "managed_futures", "xs_momentum", "low_vol",
                      "premium_vrp", "premium_earnings")

    # EXIT-PRICE PROVENANCE LADDER (strongest -> weakest), the hybrid confirmation model:
    #   _CONFIRMED_BASES     — the ACTUAL executed fill price (real SIM option fills, or a sleeve close
    #                          upgraded to the executed sell price). Gold standard.
    #   _MARK_CONFIRM_BASES  — broker CONFIRMED the quantity (reconcile saw the held-qty drop), priced at
    #                          the mark at that instant. A real fill in quantity, mark-priced. The hybrid
    #                          FLOOR: counts as confirmed (the SIM broker doesn't durably expose executed
    #                          fill prices, so insisting on them would block every verdict forever), with a
    #                          small mark-vs-fill slippage the court surfaces honestly.
    #   _ESTIMATE_BASES      — a genuine ESTIMATE not tied to a confirmed-quantity instant (defined-risk
    #                          condor mids; a late/loose quote). A verdict resting mostly on these stays
    #                          PROVISIONAL — the court never presents an estimate-priced edge as settled.
    _CONFIRMED_BASES = ("fills", "fill_net")
    _MARK_CONFIRM_BASES = ("mark_at_confirm",)
    _ESTIMATE_BASES = ("mid_estimate", "quote", "quote_estimate", "later_estimate")

    def _execution_cost_by_sleeve(self):
        """Per-sleeve MEASURED execution slippage (decision-mid vs fill) from ExecutionLog. A DIAGNOSTIC
        shown BESIDE each edge — deliberately NOT subtracted from realized_pnl, which is already computed
        from actual fills (the execution cost is already IN the number; subtracting again double-counts).
        Pair rule: a sleeve whose measured slippage exceeds its edge is a retire candidate. The condor
        sleeves aren't instrumented in ExecutionLog yet — their realized_pnl is fill-based regardless."""
        try:
            from app.services.execution_log_engine import ExecutionLogEngine
            by = ExecutionLogEngine().realized().get("by_strategy") or {}
        except Exception:
            by = {}
        out = {}
        for sleeve in self._COURT_SLEEVES:
            strat = self._EXEC_STRATEGY.get(sleeve)
            src = by.get(strat) if strat else None
            if src:
                # "measured" only if a fill was actually reconciled; an instrumented-but-empty strategy row
                # (orders placed, no fills yet) has no slippage to report — don't dress it up as measured.
                reconciled = src.get("avg_slippage_bps") is not None or bool(src.get("fill_rate_pct"))
                out[sleeve] = {"avg_slippage_bps": src.get("avg_slippage_bps"),
                               "fill_rate_pct": src.get("fill_rate_pct"),
                               "realized_slippage_usd": src.get("realized_slippage_usd"),
                               "source": "measured" if reconciled else "instrumented — no fills reconciled yet"}
            elif strat:
                out[sleeve] = {"source": "instrumented — no orders logged yet"}
            else:
                out[sleeve] = {"source": "not instrumented (realized P&L is already fill-net)"}
        return out

    @staticmethod
    def _risk_basis_label(ts):
        """Report the risk denominator honestly: one kind if the sleeve's closed trades are homogeneous,
        else 'mixed (...)' so a blended equity sleeve (some exact stops, some vol proxies) isn't presented
        as if every trade used the same basis."""
        kinds = sorted({t.get("risk_kind") for t in ts if t.get("risk_kind")})
        if not kinds:
            return None
        if len(kinds) == 1:
            return kinds[0]
        return "mixed (" + ", ".join(kinds) + ")"

    @staticmethod
    def _trade_day(closed_at):
        """The trading-day key for correlation clustering: the YYYY-MM-DD date of the close. Rows without a
        parseable date collapse into a single 'unknown' bucket (conservative — never SPLIT a fuzzy row into
        multiple independent samples)."""
        s = str(closed_at or "")
        return s[:10] if (len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-") else "unknown"

    @classmethod
    def _daily_returns(cls, ts):
        """INDEPENDENCE by day-clustering. Multiple lots/tranches closed in the same instant, and multiple
        names closed by one same-day rebalance, are ONE correlated observation — not many independent
        samples. Counting each row independently inflated the t-stat by ~sqrt(fake n) and let a single
        close masquerade as a proven track record (vol_carry: 5 same-instant SVXY lots → a fake t=10.8).
        The statistical unit is the TRADING DAY: each day contributes one risk-weighted return
        (sum net / sum risk over that day's closes). Returns a sorted list of per-day observations."""
        by_day = {}
        for t in ts:
            r = t.get("risk")
            if not (r and r > 0):
                continue
            d = by_day.setdefault(cls._trade_day(t.get("closed_at")), {"net": 0.0, "risk": 0.0, "closes": 0})
            d["net"] += t["net"]
            d["risk"] += r
            d["closes"] += 1
        out = []
        for day, agg in sorted(by_day.items()):
            if agg["risk"] > 0:
                out.append({"day": day, "net": agg["net"], "risk": agg["risk"],
                            "closes": agg["closes"], "ror": agg["net"] / agg["risk"]})
        return out

    def realized_edge(self):
        trades, excluded = self._closed_trades()
        by = {}
        for t in trades:
            by.setdefault(t["sleeve"], []).append(t)

        sleeves = {}
        for sleeve, ts in by.items():
            # Day-clustered: the sample is DISTINCT TRADING DAYS, not raw close-rows (tranches/legs of one
            # close are correlated, not independent). Each day = one risk-weighted return.
            daily = self._daily_returns(ts)
            rets = [d["ror"] for d in daily]
            n = len(rets)                                    # independent trading days — the real sample size
            n_closes = len(ts)                               # raw close rows (lots/legs), for context only
            mean = sum(rets) / n if n else 0.0
            wins = sum(1 for d in daily if d["net"] > 0)     # winning DAYS, not winning tranches
            lo = hi = None
            t_stat = 0.0
            stat = {"trades": n, "independent_days": n, "closes": n_closes,
                    "wins": wins, "win_rate": round(wins / n, 2) if n else None,
                    "mean_return_on_risk_pct": round(mean * 100, 2) if n else None,
                    "total_net_pnl": round(sum(t["net"] for t in ts), 2),
                    "risk_basis": self._risk_basis_label(ts)}   # instrument-aware denominator (honest if mixed)
            if n >= 2:
                var = sum((r - mean) ** 2 for r in rets) / (n - 1)
                sd = math.sqrt(var)
                se = sd / math.sqrt(n)
                t_stat = mean / se if se > 0 else 0.0
                tc = self._t_crit(n)                     # small-sample-aware, not the flat 1.96
                lo, hi = mean - tc * se, mean + tc * se
                stat.update({"std_return_on_risk_pct": round(sd * 100, 2), "t_stat": round(t_stat, 2),
                             "t_crit": round(tc, 3), "ci95_return_on_risk_pct": [round(lo * 100, 2), round(hi * 100, 2)]})

            if n < self.MIN_TRADES:
                verdict = (f"ACCUMULATING ({n}/{self.MIN_TRADES} independent trading days — too few to judge"
                           + (f"; {n_closes} close-rows" if n_closes != n else "") + ")")
            elif lo is not None and lo > 0 and mean >= self.MIN_EDGE_ROR:
                verdict = "PROVEN — cost-net edge > 0 at 95% (small-sample t) and above the action floor"
            elif hi is not None and hi < 0:
                verdict = "DECAYED — cost-net edge < 0 at 95% (small-sample t); retire"
            elif lo is not None and lo > 0:              # significant but too small to act on
                verdict = (f"UNPROVEN — statistically positive but mean {round(mean * 100, 2)}% "
                           f"< {round(self.MIN_EDGE_ROR * 100, 2)}% action floor")
            else:
                verdict = "UNPROVEN — edge indistinguishable from zero net of cost"
            # Exit-price provenance honesty (hybrid model): split this sleeve's exits into EXECUTED fills,
            # MARK-AT-CONFIRM (broker-confirmed quantity, mark-priced), and genuine ESTIMATES. Only genuine
            # estimates make a verdict PROVISIONAL — mark-at-confirm counts as confirmed (a real fill in
            # quantity), so verdicts can progress, but the court still SHOWS how many are executed-price vs
            # mark-priced so nothing dresses a mark-priced edge up as executed truth. (hybrid 2026-08-11)
            executed = sum(1 for t in ts if str(t.get("basis")) in self._CONFIRMED_BASES)
            mark_conf = sum(1 for t in ts if str(t.get("basis")) in self._MARK_CONFIRM_BASES)
            est = len(ts) - executed - mark_conf          # anything not confirmed/mark-confirmed = estimate
            stat["executed_fill_trades"] = executed
            stat["mark_confirmed_trades"] = mark_conf
            stat["estimated_trades"] = est
            stat["fill_confirmed_trades"] = executed + mark_conf     # confirmed-enough (executed + mark-at-confirm)
            if est and est > len(ts) / 2:
                stat["fill_confirmation"] = (f"{est}/{len(ts)} exits are genuine price ESTIMATES (e.g. condor "
                                             "mids), not confirmed — verdict provisional until they reconcile")
                verdict += f" · PROVISIONAL ({est}/{len(ts)} exits estimate-priced)"
            elif mark_conf and not executed:
                stat["fill_confirmation"] = (f"{mark_conf}/{len(ts)} exits are MARK-AT-CONFIRM (broker-confirmed "
                                             "quantity, mark-priced at the fill instant); 0 upgraded to executed "
                                             "fill prices (this SIM broker doesn't durably expose them)")
            else:
                stat["fill_confirmation"] = (f"{executed} executed-fill + {mark_conf} mark-at-confirm of "
                                             f"{len(ts)} exits confirmed")
            stat["verdict"] = verdict
            stat["_t"] = t_stat
            sleeves[sleeve] = stat

        # closest-to-proven: the sleeve to push resources at first (highest t-stat among the unproven)
        ranked = sorted(sleeves.items(), key=lambda kv: kv[1].get("_t", 0.0), reverse=True)
        closest = [{"sleeve": k, "trades": v["trades"], "independent_days": v.get("independent_days"),
                    "closes": v.get("closes"), "t_stat": v.get("t_stat"),
                    "mean_return_on_risk_pct": v["mean_return_on_risk_pct"], "verdict": v["verdict"]}
                   for k, v in ranked]
        for v in sleeves.values():
            v.pop("_t", None)

        return {
            "sleeves": sleeves,
            "closest_to_proven": closest,
            "execution_cost": self._execution_cost_by_sleeve(),
            "execution_cost_note": ("MEASURED slippage (ExecutionLog decision-mid vs fill), shown beside "
                                    "each edge — NOT re-subtracted (realized_pnl is already fill-net). A "
                                    "sleeve whose measured cost exceeds its edge is a retire candidate."),
            "excluded_forced_closes": excluded,
            "min_trades_gate": self.MIN_TRADES,
            "min_trades_gate_unit": "independent trading days (day-clustered, not raw close-rows)",
            "cost_note": ("cost-net: equity/option closes use real SIM fills; condor closes are priced from "
                          "actual close fills or the marketable close-order debit (basis fills/close_order) — "
                          f"already honest, no haircut. Only LEGACY mid-marked condor rows are haircut "
                          f"{self.CONDOR_CLOSE_HAIRCUT_FRAC*100:.0f}% of max-loss as a conservative proxy."),
            "method": ("day-clustered return on risk: the sample is DISTINCT TRADING DAYS (each day = one "
                       "risk-weighted return), NOT raw close-rows — same-instant tranches and same-day "
                       "rebalance legs are correlated, so counting them independently would inflate the "
                       "t-stat by ~sqrt(fake n). 'trades' = independent days; 'closes' = raw rows. PROVEN "
                       f"needs the SMALL-SAMPLE-t 95% CI above 0 AND a mean >= {self.MIN_EDGE_ROR * 100:.1f}% "
                       "action floor (a significant-but-trivial edge won't fire capital moves); DECAYED needs "
                       "the CI below 0. Realized CLOSED trades only, forced flattens excluded. Daily "
                       "open-marks are autocorrelated and are NEVER used."),
            "multiple_comparison_note": (f"{len(sleeves)} sleeve(s) verdicted; each uses a per-sleeve test on "
                                         "PRE-SPECIFIED strategies (not a search), so no Bonferroni — but treat a "
                                         "lone borderline PROVEN with caution and prefer more trades."),
            "risk_basis_note": (f"return-on-risk divides by INSTRUMENT-AWARE intended max loss: condor = defined "
                                f"max_loss; long option = premium paid; equity = the doctrine's recorded initial "
                                f"stop distance ('stop_atr_doctrine', EXACT) when stamped at entry, else a "
                                f"{int(self.EQUITY_STOP_PCT*100)}% ~2.5-ATR PROXY. So momentum's ROR and the "
                                "closest-to-proven ranking are comparable with the condors', not vs raw notional."),
        }

    def decay_alert(self, dispatch=True):
        """Fire on any sleeve the court has judged DECAYED (cost-net edge < 0 at 95%, ≥ MIN_TRADES).
        This is the RETIRE half of the measure→retire discipline: a losing edge must not silently bleed.
        Deduped by the stable sorted set of decayed sleeves, so it pages ONCE per new decay, not every
        cycle. Read-only + best-effort — never trades, never raises."""
        try:
            sleeves = self.realized_edge().get("sleeves") or {}
        except Exception as e:
            return {"status": "EDGE_DECAY_DEGRADED", "error": repr(e)[:100]}
        decayed = sorted(s for s, v in sleeves.items() if str(v.get("verdict", "")).startswith("DECAYED"))
        if not decayed:
            return {"status": "EDGE_DECAY_NONE", "decayed": []}
        detail = "; ".join(
            f"{s}: n={sleeves[s].get('trades')}, mean {sleeves[s].get('mean_return_on_risk_pct')}% on risk "
            f"(95% CI {sleeves[s].get('ci95_return_on_risk_pct')})" for s in decayed)
        if dispatch:
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                eng = ExternalAlertEngine()
                if eng.has_external_channel():
                    eng.dispatch(
                        title="GreyLine sleeve DECAYED — candidate to retire",
                        message=(f"The edge court judged {len(decayed)} sleeve(s) DECAYED (cost-net edge < 0 "
                                 f"at 95% confidence, ≥{self.MIN_TRADES} trades): {detail}. Consider retiring "
                                 "or cutting its capital. See the Edge Court card / /edge-persistence."),
                        severity="WARNING", fingerprint=f"EDGE_DECAYED:{','.join(decayed)}")
            except Exception:
                pass
        return {"status": "EDGE_DECAY_FLAGGED", "decayed": decayed, "detail": detail}

    # ---------------------------------------------------------------- open-position drift (CONTEXT)

    def _rows(self):
        return self._read(self.LEDGER)

    def snapshot(self):
        """Record today's per-sleeve OPEN-position marks (one set per UTC day; last wins). Context only."""
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            positions = BrokerAccountViewEngine().snapshot().get("positions", []) or []
        except Exception as e:
            return {"status": "EDGE_PERSISTENCE_DEGRADED", "error": repr(e)[:100]}

        today = datetime.utcnow().date().isoformat()
        agg = {}
        for p in positions:
            s = self._sleeve_of(p.get("symbol"), p.get("asset_type") or p.get("AssetType"))
            a = agg.setdefault(s, {"deployed": 0.0, "unrealized": 0.0, "market_value": 0.0, "positions": 0})
            a["deployed"] += self._f(p.get("entry_price")) * self._f(p.get("quantity"))
            a["unrealized"] += self._f(p.get("unrealized_pnl"))
            a["market_value"] += self._f(p.get("current_price")) * self._f(p.get("quantity"))
            a["positions"] += 1

        rows = [r for r in self._rows() if r.get("date") != today]
        for sleeve, a in agg.items():
            rows.append({"date": today, "sleeve": sleeve,
                         "deployed": round(a["deployed"], 2), "unrealized": round(a["unrealized"], 2),
                         "market_value": round(a["market_value"], 2), "positions": a["positions"],
                         "ts": datetime.utcnow().isoformat()})
        try:
            self.DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        except Exception as e:
            return {"status": "EDGE_PERSISTENCE_WRITE_FAILED", "error": repr(e)[:100]}
        return {"status": "EDGE_PERSISTENCE_RECORDED", "date": today,
                "sleeves": {s: round(a["unrealized"], 2) for s, a in agg.items()}}

    def _open_drift(self):
        by = {}
        for r in self._rows():
            by.setdefault(r.get("sleeve"), []).append(r)
        out = {}
        for sleeve, recs in by.items():
            recs.sort(key=lambda x: x.get("date", ""))
            days = len(recs)
            neg = sum(1 for r in recs if self._f(r.get("unrealized")) < 0)
            out[sleeve] = {"days_tracked": days,
                           "current_unrealized": self._f(recs[-1].get("unrealized")),
                           "negative_day_fraction": round(neg / max(1, days), 2)}
        return out

    def report(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "realized_edge": self.realized_edge(),
            "open_drift": self._open_drift(),
            "note": ("AUTHORITATIVE verdict = realized_edge (closed trades, cost-net, CI-gated). open_drift "
                     "is unrealized daily marks for context only — autocorrelated, NOT evidence of edge."),
            "status": "EDGE_PERSISTENCE_REPORT",
        }
