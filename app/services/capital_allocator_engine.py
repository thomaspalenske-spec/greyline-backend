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
    DRIFT_USD = 400.0           # material divergence: recommended vs live budget for a sleeve
    DRIFT_PCT = 0.04            # ...or this fraction of equity, whichever is larger

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

    # COURT-INFORMED PRE-PROVEN TILT — GATED OFF by default (GREYLINE_COURT_ALLOC_TILT_ENABLED).
    # Below the 20-trade verdict gate the court's accumulating evidence is otherwise ignored ENTIRELY.
    # This leans a sleeve's PRIOR weight toward that evidence by a TINY, sample-shrunk, hard-capped amount
    # — never pretending a thin sample is a verdict (that is the documented false-confidence trap). It is
    # symmetric (negative evidence tilts DOWN), auto-disabled the instant a sleeve reaches the gate (the
    # measured override takes over), stateless/fully reversible, and shows its would-be value even when off.
    TILT_MIN_TRADES = 8          # never tilt below this — a smaller sample is indistinguishable from noise
    TILT_MAX_FRAC = 0.15         # HARD cap: the tilt moves a sleeve's prior weight at most +/-15%
    TILT_T_REF = 2.0             # t-stat mapping to full (pre-shrink) signal — ~the 95% significance mark

    @classmethod
    def _tilt_enabled(cls):
        return (getenv("GREYLINE_COURT_ALLOC_TILT_ENABLED", "") or "").strip().lower() == "true"

    def _court_tilt(self, stats, gate):
        """Bounded, sample-shrunk lean toward a BELOW-gate sleeve's accumulating court evidence.
        Returns (applied_frac, detail). The signal is sign(mean return-on-risk) x t-stat confidence
        (capped at 1 via TILT_T_REF) x a shrink factor n/gate (→0 as the sample thins), then clamped to
        +/- TILT_MAX_FRAC. applied is 0 unless the tilt is ENABLED and the sleeve is eligible (n in
        [TILT_MIN_TRADES, gate), non-flat); `would_be` is always shown for transparency."""
        n = int((stats or {}).get("trades") or 0)
        mean = self._f((stats or {}).get("mean_return_on_risk_pct"))
        t = abs(self._f((stats or {}).get("t_stat")))
        eligible = n >= self.TILT_MIN_TRADES and n < gate and mean != 0.0
        would = 0.0
        if eligible:
            direction = 1.0 if mean > 0 else -1.0
            confidence = min(1.0, t / self.TILT_T_REF)        # 0..1 by significance (pre-shrink)
            shrink = min(1.0, n / float(gate))                # 0..1 by closeness to a real verdict
            would = round(max(-self.TILT_MAX_FRAC,
                              min(self.TILT_MAX_FRAC, direction * confidence * shrink * self.TILT_MAX_FRAC)), 4)
        enabled = self._tilt_enabled()
        applied = would if (enabled and eligible) else 0.0
        if not eligible:
            reason = (f"n {n} < {self.TILT_MIN_TRADES}-trade floor — too thin to lean on"
                      if n < self.TILT_MIN_TRADES else
                      "at/above the verdict gate — measured override takes over" if n >= gate
                      else "evidence flat (mean 0)")
        elif not enabled:
            reason = "would tilt but DISABLED (GREYLINE_COURT_ALLOC_TILT_ENABLED=false)"
        else:
            reason = f"pre-proven lean: {n}/{gate} trades, sample-shrunk & capped at {int(self.TILT_MAX_FRAC*100)}%"
        return applied, {"applied": applied, "would_be": would, "n": n,
                         "mean_ror_pct": mean, "t_stat": round(t, 2), "reason": reason}

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
            # days-tracked now lives under open_drift (the daily-mark history); the realized-edge court
            # is the authoritative verdict but gates on CLOSED trades, not calendar days.
            rows = EdgePersistenceEngine().report().get("open_drift", {})
            days = max((v.get("days_tracked", 0) for v in rows.values()), default=0)
            if days >= self.MIN_LIVE_DAYS:
                return "live", days
            return "backtest_priors", days
        except Exception:
            return "backtest_priors", 0

    def _current_allocs(self, equity):
        # Live sleeve budgets are now %-of-equity via SleeveCapitalBudgetEngine (the recommendation
        # compares its evidence-based target against the ACTUAL live budget, so read from there).
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as B
            return {
                "trend": B.budget_usd("trend"),
                "carry": B.budget_usd("vol_carry"),
                "momentum": B.budget_usd("momentum"),
                "vrp": B.budget_usd("vrp", clamp_to_cash=False),
                "earnings": B.budget_usd("earnings", clamp_to_cash=False),
            }
        except Exception:
            return {
                "trend": self._f(getenv("GREYLINE_TREND_ALLOC_USD"), 3000),
                "carry": self._f(getenv("GREYLINE_VOL_CARRY_ALLOC_USD"), 2000),
                "momentum": self._f(getenv("GREYLINE_MOMENTUM_CAPITAL_USD"), 10000),
                "vrp": 1200.0, "earnings": 900.0,        # risk caps
            }

    def drift_alert(self, dispatch=True):
        """Page (deduped) when a MEASURED court verdict has drifted the evidence-based recommendation
        materially from the LIVE budget — i.e. it's time to approve a re-allocation. Scoped to
        measured-basis sleeves only (a gated PROVEN/DECAYED/UNPROVEN verdict), NOT the standing
        prior-vs-live divergence (e.g. momentum), which the operator has already decided on and which
        would otherwise be repeat noise. Deduped by the set of drifting sleeves + basis, so it fires
        once per NEW evidence state. Read-only, recommendation-only — never trades. Best-effort."""
        try:
            r = self.recommend()
        except Exception as e:
            return {"status": "ALLOC_DRIFT_DEGRADED", "error": repr(e)[:100]}
        equity = self._f(r.get("equity"), 10000.0)
        thresh = max(self.DRIFT_USD, self.DRIFT_PCT * equity)
        drifts = []
        for s, v in (r.get("sleeves") or {}).items():
            if not str(v.get("basis") or "").startswith("measured"):     # evidence-driven only
                continue
            delta = self._f(v.get("delta_usd"))
            if abs(delta) >= thresh:
                drifts.append({"sleeve": s, "recommended_usd": v.get("recommended_usd"),
                               "current_usd": v.get("current_usd"), "delta_usd": delta,
                               "basis": str(v.get("basis"))})
        if not drifts:
            return {"status": "ALLOC_DRIFT_NONE", "drifts": [], "threshold_usd": round(thresh)}
        drifts.sort(key=lambda d: d["sleeve"])
        fingerprint = "ALLOC_DRIFT:" + ",".join(f"{d['sleeve']}:{d['basis']}" for d in drifts)
        decayed = any(d["basis"] == "measured_decayed" for d in drifts)
        if dispatch:
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                eng = ExternalAlertEngine()
                if eng.has_external_channel():
                    detail = "; ".join(
                        f"{d['sleeve']} ${self._f(d['current_usd']):.0f}->${self._f(d['recommended_usd']):.0f} "
                        f"({d['delta_usd']:+.0f}, {d['basis'].replace('measured_', '')})" for d in drifts)
                    eng.dispatch(
                        title="GreyLine capital re-alloc recommended",
                        message=(f"A measured court verdict drifted the evidence-based allocation from the live "
                                 f"book on {len(drifts)} sleeve(s) (≥ ${round(thresh)}): {detail}. Review "
                                 "/capital-allocator + the Edge Court; applying is an after-hours operator step."),
                        severity=("WARNING" if decayed else "INFO"), fingerprint=fingerprint)
            except Exception:
                pass
        return {"status": "ALLOC_DRIFT_FLAGGED", "drifts": drifts, "threshold_usd": round(thresh)}

    def recommend(self):
        equity = self._equity()
        basis, days = self._basis()
        risk_on = self.RISK_ON_PCT * equity

        # MEASURED OVERRIDE: once a sleeve has a GATED court verdict (>= the min-trades gate), capital
        # follows the MEASURED edge, not the prior — PROVEN funds it (evidence-2-equivalent), DECAYED
        # zeroes it (retire), UNPROVEN-after-the-gate drops it to a probe (it had its chance). Below the
        # gate, or no verdict, the backtest prior stands. This is what makes capital flow to what the
        # court proves and away from what it retires. Maps allocator sleeves -> court sleeve keys.
        court, court_pre, gate = {}, {}, 20
        try:
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            _re = EdgePersistenceEngine().realized_edge()
            gate = int(_re.get("min_trades_gate") or 20)
            _MAP = {"vrp": "premium_vrp", "earnings": "premium_earnings",
                    "momentum": "momentum", "carry": "carry", "trend": "trend"}
            _cs = _re.get("sleeves") or {}
            for a, c in _MAP.items():
                v = _cs.get(c)
                if not v:
                    continue
                if int(v.get("trades") or 0) >= gate:
                    court[a] = v            # gated verdict -> measured override
                else:
                    court_pre[a] = v        # below the gate -> candidate for the pre-proven tilt
        except Exception:
            court, court_pre = {}, {}

        # raw score per sleeve: evidence tier x risk-parity (target/vol) x correlation penalty
        raw, basis_of, tilt_of = {}, {}, {}
        for s, p in self.PRIORS.items():
            cv = court.get(s)
            if cv:
                verdict = str(cv.get("verdict", ""))
                if verdict.startswith("PROVEN"):
                    w, basis_of[s] = 2.0 * (self.TARGET_VOL / p["vol"]) * p["corr_pen"], "measured_proven"
                elif verdict.startswith("DECAYED"):
                    w, basis_of[s] = 0.0, "measured_decayed"
                else:                                 # UNPROVEN after the gate -> probe only
                    w, basis_of[s] = self.PROBE_WEIGHT * (self.TARGET_VOL / p["vol"]) * p["corr_pen"], "measured_unproven"
            else:
                ev = p["evidence"]
                if ev < 0:                            # no-edge -> zero
                    w = 0.0
                elif ev == 0:                         # unproven -> small probe
                    w = self.PROBE_WEIGHT * (self.TARGET_VOL / p["vol"]) * p["corr_pen"]
                else:
                    w = ev * (self.TARGET_VOL / p["vol"]) * p["corr_pen"]
                basis_of[s] = "prior"
                # COURT-INFORMED PRE-PROVEN TILT: a tiny, sample-shrunk, capped lean toward accumulating
                # evidence (only when enabled + eligible). A zero-weight sleeve (no-edge prior) is left at
                # zero — the tilt scales an existing weight, it never funds a sleeve the prior zeroed.
                applied, tdet = self._court_tilt(court_pre.get(s), gate)
                tilt_of[s] = tdet
                if applied != 0.0 and w > 0.0:
                    w = max(0.0, w * (1.0 + applied))
                    basis_of[s] = "prior+tilt"
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
            cv = court.get(s)
            sleeves[s] = {"recommended_usd": rec[s], "recommended_pct": round(100 * rec[s] / equity, 1),
                          "current_usd": round(current.get(s, 0), 0),
                          "delta_usd": round(rec[s] - current.get(s, 0), 0),
                          "evidence": p["evidence"], "basis": basis_of[s],
                          "court_tilt": tilt_of.get(s),
                          "why": (f"court {cv.get('verdict')}" if cv else p["note"])}
        measured = sorted(court)
        tilted = sorted(s for s, d in tilt_of.items() if d and d.get("applied"))
        return {
            "timestamp": datetime.utcnow().isoformat(), "equity": equity,
            "basis": ("measured (court) where gated, else backtest priors" if measured else basis),
            "measured_sleeves": measured, "trade_gate": gate,
            "court_tilt_enabled": self._tilt_enabled(),
            "court_tilt_applied_sleeves": tilted,
            "court_tilt_note": (f"pre-proven tilt: a capped +/-{int(self.TILT_MAX_FRAC*100)}%, sample-shrunk "
                                f"lean toward accumulating court evidence for below-gate sleeves with "
                                f">= {self.TILT_MIN_TRADES} trades. GATED OFF by default; auto-disabled once "
                                "a sleeve reaches the verdict gate. Shows would_be even when off."),
            "live_days_available": days, "min_live_days_needed": self.MIN_LIVE_DAYS,
            "risk_on_target_pct": round(100 * self.RISK_ON_PCT), "sleeves": sleeves,
            "tbill_cash_residual_usd": tbill_cash,
            "headline": ("On the evidence, momentum -> ~$%.0f (no edge), the book concentrates in "
                         "trend+carry, VRP modest, earnings a small probe." % rec["momentum"]
                         + (f" MEASURED override active for: {', '.join(measured)}." if measured else "")),
            "note": ("RECOMMENDATION ONLY — does not change allocations or trade. Applying it is an "
                     "after-hours, operator-approved step. A sleeve with a GATED court verdict (>= "
                     f"{gate} trades) follows the MEASURED edge (PROVEN funds / DECAYED zeroes / UNPROVEN "
                     "probes); the rest use the backtest priors until they cross the gate."),
            "status": "CAPITAL_ALLOCATOR_RECOMMENDATION",
        }
