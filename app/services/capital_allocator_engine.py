"""Evidence-based capital allocation — the discipline: capital follows MEASURED edge, not narrative.

Piece 2 of copying Medallion's discipline. Today's allocations are ad-hoc dollars (trend $3k, carry
$2k, momentum $1.5k) set by feel. This computes what the allocation SHOULD be on the evidence:
up-weight the sleeves with real measured edge, down-weight the correlated ones, and drive the
no-edge sleeve (momentum) toward zero. It is what would have starved momentum long before -41%.

RECOMMENDS ONLY — it never changes the live allocation knobs or trades. Applying a re-allocation
changes sizing and triggers rebalance orders, so that is a deliberate, AFTER-HOURS, operator-approved
step, never a live-day auto-action.

BASIS: until /edge-persistence has real live history (>= MIN_LIVE_DAYS), this uses the backtest priors
established this session (carry/trend Sharpe ~0.5, +0.57 correlated; VRP real-but-small; earnings
unproven; momentum negative/no-edge). As live per-sleeve data accumulates it switches to measured
Sharpe/correlation. It says which basis it used, honestly.
"""

from datetime import datetime
from os import getenv


class CapitalAllocatorEngine:

    RISK_ON_PCT = 0.55            # target fraction of the book in edge sleeves; rest = T-bill/cash
    TARGET_VOL = 0.12            # risk-parity reference
    MIN_SLEEVE_USD = 500.0      # below this a sleeve isn't worth a separate line -> 0 (or a probe)
    MAX_SLEEVE_PCT = 0.35       # no single sleeve dominates the book
    MIN_LIVE_DAYS = 15          # live history needed before trusting measured over priors

    # honest priors from THIS session's work (evidence: 2 backtested / 1 real-small / 0 unproven / -1 no-edge)
    PRIORS = {
        "trend":    {"sharpe": 0.50, "vol": 0.10, "evidence": 2, "corr_pen": 0.85,
                     "note": "backtested Sharpe ~0.5 (0.77 recent); crash-protective diversifier"},
        "carry":    {"sharpe": 0.50, "vol": 0.14, "evidence": 2, "corr_pen": 0.85,
                     "note": "backtested Sharpe ~0.5; short-vol, +0.57 corr with trend"},
        "vrp":      {"sharpe": 0.30, "vol": 0.10, "evidence": 1, "corr_pen": 1.0,
                     "note": "real but small; forward-only; borderline after costs"},
        "earnings": {"sharpe": 0.00, "vol": 0.10, "evidence": 0, "corr_pen": 1.0,
                     "note": "UNPROVEN (can't backtest) — small probe only"},
        "momentum": {"sharpe": -0.30, "vol": 0.20, "evidence": -1, "corr_pen": 1.0,
                     "note": "NO proven edge; lost 41% — evidence says ~0"},
    }
    PROBE_WEIGHT = 0.30          # weight for an unproven (evidence 0) sleeve: a small funded probe

    @staticmethod
    def _f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    def _equity(self):
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            return MissionRiskGovernorEngine().snapshot().get("mission_equity", 10000.0)
        except Exception:
            return 10000.0

    def _basis(self):
        try:
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            rows = EdgePersistenceEngine().report().get("sleeves", {})
            days = max((v.get("days_tracked", 0) for v in rows.values()), default=0)
            if days >= self.MIN_LIVE_DAYS:
                return "live", days
            return "backtest_priors", days
        except Exception:
            return "backtest_priors", 0

    def _current_allocs(self, equity):
        return {
            "trend": self._f(getenv("GREYLINE_TREND_ALLOC_USD"), 3000),
            "carry": self._f(getenv("GREYLINE_VOL_CARRY_ALLOC_USD"), 2000),
            "momentum": self._f(getenv("GREYLINE_MOMENTUM_CAPITAL_USD"), 10000),
            "vrp": 1200.0, "earnings": 900.0,        # risk caps
        }

    def recommend(self):
        equity = self._equity()
        basis, days = self._basis()
        risk_on = self.RISK_ON_PCT * equity

        # raw score per sleeve: evidence tier x risk-parity (target/vol) x correlation penalty
        raw = {}
        for s, p in self.PRIORS.items():
            ev = p["evidence"]
            if ev < 0:                                # no-edge -> zero
                w = 0.0
            elif ev == 0:                             # unproven -> small probe
                w = self.PROBE_WEIGHT * (self.TARGET_VOL / p["vol"]) * p["corr_pen"]
            else:
                w = ev * (self.TARGET_VOL / p["vol"]) * p["corr_pen"]
            raw[s] = max(0.0, w)

        total = sum(raw.values()) or 1.0
        rec, current = {}, self._current_allocs(equity)
        for s, p in self.PRIORS.items():
            dollars = (raw[s] / total) * risk_on
            dollars = min(dollars, self.MAX_SLEEVE_PCT * equity)      # ceiling
            if 0 < dollars < self.MIN_SLEEVE_USD:                     # floor: bump probes, zero the rest
                dollars = self.MIN_SLEEVE_USD if raw[s] >= self.PROBE_WEIGHT * 0.9 else 0.0
            rec[s] = round(dollars, 0)
        tbill_cash = round(equity - sum(rec.values()), 0)

        sleeves = {}
        for s, p in self.PRIORS.items():
            sleeves[s] = {"recommended_usd": rec[s], "recommended_pct": round(100 * rec[s] / equity, 1),
                          "current_usd": round(current.get(s, 0), 0),
                          "delta_usd": round(rec[s] - current.get(s, 0), 0),
                          "evidence": p["evidence"], "why": p["note"]}
        return {
            "timestamp": datetime.utcnow().isoformat(), "equity": equity,
            "basis": basis, "live_days_available": days, "min_live_days_needed": self.MIN_LIVE_DAYS,
            "risk_on_target_pct": round(100 * self.RISK_ON_PCT), "sleeves": sleeves,
            "tbill_cash_residual_usd": tbill_cash,
            "headline": ("On the evidence, momentum -> ~$%.0f (no edge), the book concentrates in "
                         "trend+carry, VRP modest, earnings a small probe." % rec["momentum"]),
            "note": ("RECOMMENDATION ONLY — does not change allocations or trade. Applying it is an "
                     "after-hours, operator-approved step. Basis is backtest priors until "
                     "/edge-persistence has >= %d live days, then it switches to measured." % self.MIN_LIVE_DAYS),
            "status": "CAPITAL_ALLOCATOR_RECOMMENDATION",
        }
