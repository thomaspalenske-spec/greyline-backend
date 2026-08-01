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

    CARRY = {"SVXY"}
    TREND = {"QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"}
    TBILL = {"SGOV"}
    MIN_DAYS = 10                       # open-drift context needs this much history to even show
    MIN_TRADES = 20                     # below this, NO realized verdict — too few samples to judge
    Z95 = 1.96                          # normal approx for the 95% CI (small-N caveat surfaced)
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
                           "risk": risk, "closed_at": r.get("closed_at"), "basis": tag})

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
            mult = 100 if str(r.get("asset_type") or "").upper() in ("STOCKOPTION", "OPTION") else 1
            qty = self._f(r.get("original_quantity")) or self._f(r.get("quantity"))
            risk = abs(self._f(r.get("entry_price")) * mult * qty)
            if risk <= 0:
                continue
            trades.append({"sleeve": sleeve, "gross": self._f(rp), "net": self._f(rp),
                           "risk": risk, "closed_at": r.get("closed_at"), "basis": "fill_net"})
        return trades, excluded

    # court sleeve -> ExecutionLog strategy key (only the direct-to-broker equity sleeves are instrumented)
    _EXEC_STRATEGY = {"carry": "carry", "trend": "trend", "tbill": "tbill", "managed_futures": "managed_futures"}
    _COURT_SLEEVES = ("momentum", "carry", "trend", "tbill", "managed_futures", "premium_vrp", "premium_earnings")

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
                out[sleeve] = {"avg_slippage_bps": src.get("avg_slippage_bps"),
                               "fill_rate_pct": src.get("fill_rate_pct"),
                               "realized_slippage_usd": src.get("realized_slippage_usd"), "source": "measured"}
            elif strat:
                out[sleeve] = {"source": "instrumented — no orders logged yet"}
            else:
                out[sleeve] = {"source": "not instrumented (realized P&L is already fill-net)"}
        return out

    def realized_edge(self):
        trades, excluded = self._closed_trades()
        by = {}
        for t in trades:
            by.setdefault(t["sleeve"], []).append(t)

        sleeves = {}
        for sleeve, ts in by.items():
            rets = [t["net"] / t["risk"] for t in ts if t["risk"] > 0]
            n = len(rets)
            mean = sum(rets) / n if n else 0.0
            wins = sum(1 for t in ts if t["net"] > 0)
            lo = hi = None
            t_stat = 0.0
            stat = {"trades": n, "wins": wins, "win_rate": round(wins / n, 2) if n else None,
                    "mean_return_on_risk_pct": round(mean * 100, 2) if n else None,
                    "total_net_pnl": round(sum(t["net"] for t in ts), 2)}
            if n >= 2:
                var = sum((r - mean) ** 2 for r in rets) / (n - 1)
                sd = math.sqrt(var)
                se = sd / math.sqrt(n)
                t_stat = mean / se if se > 0 else 0.0
                lo, hi = mean - self.Z95 * se, mean + self.Z95 * se
                stat.update({"std_return_on_risk_pct": round(sd * 100, 2), "t_stat": round(t_stat, 2),
                             "ci95_return_on_risk_pct": [round(lo * 100, 2), round(hi * 100, 2)]})

            if n < self.MIN_TRADES:
                verdict = f"ACCUMULATING ({n}/{self.MIN_TRADES} trades — too few to judge)"
            elif lo is not None and lo > 0:
                verdict = "PROVEN — cost-net edge > 0 at 95% confidence"
            elif hi is not None and hi < 0:
                verdict = "DECAYED — cost-net edge < 0 at 95% confidence; retire"
            else:
                verdict = "UNPROVEN — edge indistinguishable from zero net of cost"
            stat["verdict"] = verdict
            stat["_t"] = t_stat
            sleeves[sleeve] = stat

        # closest-to-proven: the sleeve to push resources at first (highest t-stat among the unproven)
        ranked = sorted(sleeves.items(), key=lambda kv: kv[1].get("_t", 0.0), reverse=True)
        closest = [{"sleeve": k, "trades": v["trades"], "t_stat": v.get("t_stat"),
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
            "cost_note": ("cost-net: equity/option closes use real SIM fills; condor closes are priced from "
                          "actual close fills or the marketable close-order debit (basis fills/close_order) — "
                          f"already honest, no haircut. Only LEGACY mid-marked condor rows are haircut "
                          f"{self.CONDOR_CLOSE_HAIRCUT_FRAC*100:.0f}% of max-loss as a conservative proxy."),
            "method": ("per-trade return on risk; verdict from the 95% CI vs 0 with a minimum-sample gate. "
                       "Realized CLOSED trades only, forced flattens excluded. Daily open-marks are "
                       "autocorrelated and are NEVER used for the verdict."),
        }

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
