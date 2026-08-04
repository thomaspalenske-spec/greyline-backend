"""Pre-registered edge-proof protocol — the scientific discipline that turns "we hope it works" into a
binding, auditable test the operator's hope cannot override.

The fill-truthful court (EdgePersistenceEngine.realized_edge) already does the STATISTICS honestly:
cost-net per-trade return on risk, small-sample-t 95% CI, a MIN_TRADES gate, PROVEN/DECAYED verdicts.
What it lacks is PRE-REGISTRATION: a per-sleeve hypothesis + required N + decision threshold + KILL-RULE
frozen BEFORE the data accumulates, so the goalposts can't move after seeing results, and a retire is a
pre-committed decision rather than a discretionary one.

This engine adds exactly that thin layer:
  * a FROZEN protocol per sleeve (registered_at + content_hash — tamper-EVIDENT, an audit trail);
  * a MECHANICAL verdict against the frozen protocol using the court's realized stats (never recomputed);
  * a condor cost screen that can kill a dead-on-arrival sleeve BEFORE waiting for N trades.

It DECIDES nothing about capital on its own — it renders the verdict; arming/sizing consume it.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path


class EdgeProofProtocolEngine:

    PROTOCOL_FILE = Path("app/data/research/edge_proof_protocols.json")

    # The PRE-REGISTERED protocols. Bootstrapped once (frozen with a timestamp + content hash); the court's
    # MUTABLE global constants (MIN_TRADES / MIN_EDGE_ROR) can drift, but a registered protocol governs by
    # ITS OWN required_n / threshold — that is the whole point of pre-registration.
    #   threshold_ror_pct: the decision line on cost-net per-trade return-on-risk (%). A significant-but-
    #     trivial edge below this does NOT count as proven (capital shouldn't chase a rounding error).
    #   required_n: closed trades needed before the verdict is BINDING (retire/prove).
    DEFAULTS = {
        "premium_vrp": {
            "hypothesis": ("The conditional-VRP iron-condor sleeve earns a POSITIVE cost-net per-trade "
                           "return on defined risk — i.e. GreyLine keeps part of the variance risk premium "
                           "AFTER its 4-leg round-trip costs. (The VRP itself is literature-real; what is "
                           "unproven is net-of-retail-cost capture.)"),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 30, "threshold_ror_pct": 2.0, "alpha": 0.05,
            "kill_rule": ("at n>=required_n, if the 95% CI lower bound on cost-net return-on-risk is <= "
                          "threshold, RETIRE — the null stands, no extension, no 'give it more time'."),
        },
        "premium_earnings": {
            "hypothesis": ("The earnings-vol IV-crush condor sleeve earns a positive cost-net per-trade "
                           "return on defined risk after 4-leg round-trip costs."),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 25, "threshold_ror_pct": 2.0, "alpha": 0.05,
            "kill_rule": "at n>=required_n, CI lower bound <= threshold -> RETIRE.",
        },
        "momentum": {
            "hypothesis": ("The momentum-reversal equity sleeve earns a positive cost-net per-trade return "
                           "on risk (long-side edge net of real fills; survivorship-inflation is the risk)."),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 30, "threshold_ror_pct": 1.0, "alpha": 0.05,
            "kill_rule": "at n>=required_n, CI lower bound <= threshold -> RETIRE.",
        },
        "trend": {
            "hypothesis": ("The 200-DMA trend-following ETF sleeve earns a positive cost-net per-trade "
                           "return on risk. Cheapest to trade (ETF, no 4-leg spread) — costs won't "
                           "structurally eat it, so it is the first candidate worth the forward test."),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 25, "threshold_ror_pct": 1.0, "alpha": 0.05,
            "kill_rule": "at n>=required_n, CI lower bound <= threshold -> RETIRE.",
        },
        "vol_carry": {
            "hypothesis": ("The VIX term-structure carry sleeve (defined-risk SVXY, regime-gated) earns a "
                           "positive cost-net per-trade return on risk."),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 25, "threshold_ror_pct": 1.0, "alpha": 0.05,
            "kill_rule": "at n>=required_n, CI lower bound <= threshold -> RETIRE.",
        },
        "managed_futures": {
            "hypothesis": ("The TSMOM managed-futures sleeve earns a positive cost-net per-trade return on "
                           "risk as a crisis-convex diversifier."),
            "null": "mean cost-net return-on-risk <= threshold",
            "required_n": 25, "threshold_ror_pct": 1.0, "alpha": 0.05,
            "kill_rule": "at n>=required_n, CI lower bound <= threshold -> RETIRE.",
        },
    }

    # ---- pre-registration (freeze / audit) -----------------------------------------------------

    @staticmethod
    def _canonical(spec):
        # only the DECISION-RELEVANT fields are hashed, so a wording tweak to the hypothesis doesn't read
        # as tampering, but any change to required_n / threshold / kill-rule does.
        keyed = {k: spec.get(k) for k in ("null", "required_n", "threshold_ror_pct", "alpha", "kill_rule")}
        return json.dumps(keyed, sort_keys=True)

    @classmethod
    def _hash(cls, spec):
        return hashlib.sha256(cls._canonical(spec).encode()).hexdigest()[:16]

    def _load(self):
        try:
            return json.loads(self.PROTOCOL_FILE.read_text())
        except Exception:
            return {}

    def _save(self, data):
        self.PROTOCOL_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.PROTOCOL_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))

    def register(self, sleeve, spec, at=None, force=False):
        """Freeze a protocol for `sleeve`. Pre-registration = ONCE: refuses to overwrite an existing
        registration unless force=True, which records a NEW registration (superseding, visibly, with its
        own timestamp) rather than silently editing — a goalpost move is never silent."""
        data = self._load()
        if sleeve in data and not force:
            return {"status": "ALREADY_REGISTERED", "sleeve": sleeve,
                    "registered_at": data[sleeve].get("registered_at")}
        rec = {"sleeve": sleeve, "spec": spec, "registered_at": at or datetime.utcnow().isoformat(),
               "content_hash": self._hash(spec)}
        if sleeve in data and force:
            rec["superseded"] = {"registered_at": data[sleeve].get("registered_at"),
                                 "content_hash": data[sleeve].get("content_hash")}
        data[sleeve] = rec
        self._save(data)
        return {"status": "REGISTERED", "sleeve": sleeve, "content_hash": rec["content_hash"]}

    def bootstrap(self, at=None):
        """Register the DEFAULTS for any sleeve not yet registered (idempotent; never overwrites a frozen
        one). Safe to call every cycle."""
        registered = []
        for sleeve, spec in self.DEFAULTS.items():
            if self.register(sleeve, spec, at=at).get("status") == "REGISTERED":
                registered.append(sleeve)
        return {"status": "PROTOCOLS_BOOTSTRAPPED", "newly_registered": registered,
                "total": len(self._load())}

    # ---- mechanical verdict against the FROZEN protocol ----------------------------------------

    @staticmethod
    def _verdict(spec, stat):
        """PROVEN / RETIRE / ACCUMULATING / FAILING_EARLY strictly from the frozen protocol + the court's
        realized stats. No new statistics — the court owns those."""
        n = int((stat or {}).get("trades") or 0)
        req = int(spec.get("required_n") or 20)
        thr = float(spec.get("threshold_ror_pct") or 0.0)
        ci = (stat or {}).get("ci95_return_on_risk_pct")
        lo = ci[0] if isinstance(ci, (list, tuple)) and len(ci) == 2 else None
        hi = ci[1] if isinstance(ci, (list, tuple)) and len(ci) == 2 else None
        if n < req:
            if n >= req / 2 and hi is not None and hi < thr:
                return "FAILING_EARLY", (f"n={n}/{req} and the 95% CI is ALREADY entirely below the "
                                         f"{thr}% line — on track to fail the kill-rule.")
            return "ACCUMULATING", f"n={n}/{req} — too few closed trades for a binding verdict."
        if lo is not None and lo > thr:
            return "PROVEN", (f"n={n}>={req} and the 95% CI lower bound ({lo}%) is above the {thr}% "
                              f"decision line — cost-net edge is real by the pre-registered test.")
        return "RETIRE", (f"n={n}>={req} and the 95% CI lower bound ({lo}%) is NOT above the {thr}% line "
                          f"— the kill-rule fires: the null stands, retire the sleeve.")

    def evaluate(self):
        """Join the FROZEN protocols with the court's live realized edge and render binding verdicts."""
        protocols = self._load()
        try:
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            court = EdgePersistenceEngine().realized_edge()
            court_sleeves = court.get("sleeves") or {}
        except Exception as e:
            return {"status": "EDGE_PROOF_DEGRADED", "error": repr(e)[:120], "protocols": list(protocols)}

        results = []
        for sleeve, rec in sorted(protocols.items()):
            spec = rec.get("spec") or {}
            tampered = (rec.get("content_hash") != self._hash(spec))   # audit: frozen spec edited?
            stat = court_sleeves.get(sleeve) or {}
            verdict, reason = self._verdict(spec, stat)
            results.append({
                "sleeve": sleeve,
                "verdict": verdict,
                "reason": reason,
                "protocol": {"hypothesis": spec.get("hypothesis"), "required_n": spec.get("required_n"),
                             "threshold_ror_pct": spec.get("threshold_ror_pct"),
                             "kill_rule": spec.get("kill_rule")},
                "registered_at": rec.get("registered_at"),
                "protocol_integrity": "TAMPERED" if tampered else "INTACT",
                "live": {"trades": stat.get("trades", 0),
                         "mean_return_on_risk_pct": stat.get("mean_return_on_risk_pct"),
                         "ci95_return_on_risk_pct": stat.get("ci95_return_on_risk_pct"),
                         "win_rate": stat.get("win_rate"),
                         "court_verdict": stat.get("verdict")},
            })
        order = {"PROVEN": 0, "RETIRE": 1, "FAILING_EARLY": 2, "ACCUMULATING": 3}
        results.sort(key=lambda r: order.get(r["verdict"], 9))
        counts = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "results": results,
            "counts": counts,
            "note": ("PRE-REGISTERED verdicts: the required_n / threshold / kill-rule were frozen before "
                     "the data. PROVEN/RETIRE are BINDING at n>=required_n; the operator's hope does not "
                     "get a vote. Statistics come from the fill-truthful court, not from here."),
            "status": "EDGE_PROOF_PROTOCOL_READY",
        }

    # ---- cost screen: kill a dead-on-arrival condor BEFORE waiting for N ------------------------

    def condor_cost_screen(self, half_spread_per_share=0.03, commission_per_contract=0.65):
        """THEORETICAL dead-on-arrival screen for the LIVE condors — distinct from the forward realized
        proof above. A defined-risk iron condor breaks even (pre-cost) at win-rate = max_loss/(credit+
        max_loss). Round-trip costs REDUCE the effective credit and RAISE that required win-rate; the extra
        win-rate the cost demands is `cost_drag_pp`. The VRP only supplies a few points of EXCESS win-rate,
        so a condor whose cost_drag_pp is large is structurally dead regardless of the premium.

        Cost model (STATED, not live — needs live NBBO to be exact, but the ranking is robust): each condor
        crosses the half-spread on 4 legs at entry AND exit (8 crossings) plus per-contract commission.
        half_spread_per_share defaults to a liquid ~$0.03; single-name condors are wider in reality."""
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
        rows = []
        try:
            opens = [r for r in V()._open_rows()]
        except Exception as e:
            return {"status": "CONDOR_COST_SCREEN_DEGRADED", "error": repr(e)[:120]}
        for r in opens:
            try:
                credit = float(r.get("credit_total") or 0)
                max_loss = float(r.get("max_loss_total") or 0)
                qty = int(r.get("quantity") or 1)
                if credit <= 0:
                    # a SHORT-premium condor with <=0 credit is nonsensical — you'd be PAYING to take on
                    # defined risk with no premium to harvest. Surface it LOUDLY (a construction bug), never
                    # silently skip.
                    rows.append({"symbol": r.get("symbol"), "credit_usd": round(credit, 2),
                                 "max_loss_usd": round(max_loss, 2), "cost_drag_pp": 999.0,
                                 "screen": ("BROKEN — non-positive credit on a short-premium condor "
                                            "(paying to take risk); should never have been booked")})
                    continue
                if max_loss <= 0:
                    continue
                legs = len(r.get("legs") or []) or 4
                # 8 spread crossings (4 legs x entry+exit) x 100 mult x qty, + commission per contract-fill
                cost = (legs * 2 * half_spread_per_share * 100 * qty) + (legs * 2 * commission_per_contract * qty)
                be = max_loss / (credit + max_loss)
                be_cost = max_loss / (max(credit - cost, 0.01) + max_loss)
                drag_pp = round((be_cost - be) * 100, 2)
                rows.append({
                    "symbol": r.get("symbol"),
                    "credit_usd": round(credit, 2), "max_loss_usd": round(max_loss, 2),
                    "breakeven_win_rate": round(be, 3),
                    "round_trip_cost_usd": round(cost, 2),
                    "cost_pct_of_credit": round(100 * cost / credit, 1),
                    "cost_inflated_breakeven_win_rate": round(be_cost, 3),
                    "cost_drag_pp": drag_pp,
                    # the VRP realistically adds only a few points of excess win-rate; flag when cost alone
                    # demands more than that thin margin.
                    "screen": ("DEAD_ON_ARRIVAL — cost alone demands more excess win-rate than the VRP "
                               "plausibly supplies" if drag_pp >= 5.0 else
                               "MARGINAL — thin but possibly viable in the lowest-cost names"),
                })
            except Exception:
                continue
        rows.sort(key=lambda x: -x["cost_drag_pp"])
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cost_model": {"half_spread_per_share": half_spread_per_share,
                           "commission_per_contract": commission_per_contract,
                           "note": "STATED model (no live NBBO); single-name spreads are wider in reality."},
            "condors": rows,
            "count": len(rows),
            "interpretation": ("A defined-risk condor already needs a 67-75% win-rate to break even; cost "
                               "drag raises that. The VRP supplies only a few points of excess win-rate, so "
                               "condors with high cost_drag_pp are structurally dead — restrict the sleeve "
                               "to the lowest-cost names or retire it."),
            "status": "CONDOR_COST_SCREEN_READY",
        }
