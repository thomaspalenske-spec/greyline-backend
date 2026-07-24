"""The honest-search ledger: every edge hypothesis GreyLine has ever tested, and its verdict.

GreyLine's mission is to find an edge — any edge — big enough to profit in options. Searching
broadly is the right instinct, but a broad search is exactly how false discoveries are
manufactured: test 100 hypotheses at p<0.05 and roughly 5 will look significant on pure noise.
Correcting only WITHIN a study, as each study has done, is not enough once many studies are
run. The correction has to span the ENTIRE search.

So every hypothesis is registered here before it is tested and its verdict recorded whether it
succeeds or fails — including the nulls, which is the part that makes the arithmetic honest. A
hypothesis that "worked" is only interesting relative to how many were tried.

TWO SCREENS, APPLIED IN THIS ORDER:

  1. ECONOMIC MAGNITUDE (first, and it disqualifies most candidates)
     For OPTIONS, statistical significance is the wrong filter. An OTM round-trip costs roughly
     500-1500 bps of premium. A 0.5% effect at p=0.0001 is worthless; a 6% effect at p=0.04 is
     interesting. This screen asks only: is the effect large enough to pay the toll? The
     momentum-reversal edge (~0.23%/5d) fails it by an order of magnitude, which is why OTM
     options destroyed it — a fact that was measurable before a single trade.

  2. STATISTICAL SURVIVAL (second, family-wise across the whole registry)
     Only effects that clear the magnitude screen get tested, which keeps the multiple-testing
     burden small by construction. The threshold tightens as the registry grows: Bonferroni
     over the count of hypotheses ever tested, not just those in the current study.

Recorded verdicts so far are three nulls (informed flow, mechanical/calendar flow, PEAD). Those
are not failures of the apparatus — they are the reason any future positive can be believed.
"""

import json
from datetime import datetime
from pathlib import Path


class EdgeDiscoveryRegistryEngine:

    LEDGER = Path("app/data/research/edge_hypothesis_registry.jsonl")

    # An OTM option round-trip commonly costs 500-1500 bps of premium (spread + theta over the
    # hold). Use the low end as the hurdle so we are generous to candidates, not to ourselves.
    OPTION_ROUNDTRIP_COST_BPS = 500
    # Delta-1 / deep-ITM expression is far cheaper; kept as the alternative hurdle.
    DELTA1_ROUNDTRIP_COST_BPS = 30
    # An effect must beat the toll by this factor to be worth the execution risk.
    REQUIRED_MULTIPLE = 2.0

    def _read(self):
        out = []
        try:
            for ln in self.LEDGER.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            return []
        return out

    def screen_magnitude(self, effect_pct, horizon_days=None, leverage=1.0):
        """Screen 1: can an effect of this size pay for the instrument that expresses it?

        `effect_pct` is the raw underlying effect (e.g. a 6% drift). `leverage` is the option's
        approximate delta-leverage on the underlying move. Returns the verdict for BOTH the OTM
        and delta-1 expressions, because an effect too small for OTM options is often still
        tradeable as delta-1 — which is exactly what the momentum-reversal study concluded.
        """
        eff_bps = abs(float(effect_pct or 0)) * 100.0 * float(leverage or 1.0)
        otm_hurdle = self.OPTION_ROUNDTRIP_COST_BPS * self.REQUIRED_MULTIPLE
        d1_hurdle = self.DELTA1_ROUNDTRIP_COST_BPS * self.REQUIRED_MULTIPLE
        return {
            "effect_pct": effect_pct,
            "leverage_assumed": leverage,
            "effect_bps_after_leverage": round(eff_bps, 1),
            "otm_hurdle_bps": otm_hurdle,
            "viable_as_otm_options": bool(eff_bps >= otm_hurdle),
            "delta1_hurdle_bps": d1_hurdle,
            "viable_as_delta1": bool(eff_bps >= d1_hurdle),
            "horizon_days": horizon_days,
            "note": ("effect must clear the round-trip toll by "
                     f"{self.REQUIRED_MULTIPLE}x to justify execution risk"),
        }

    def register(self, name, hypothesis, family=None, prereg_notes=None, save=True):
        """Declare a hypothesis BEFORE testing it. Registration is what makes the count honest."""
        rec = {
            "name": name, "hypothesis": hypothesis, "family": family or "general",
            "registered_at": datetime.utcnow().isoformat(),
            "prereg_notes": prereg_notes, "verdict": None, "result": None,
        }
        if save:
            try:
                self.LEDGER.parent.mkdir(parents=True, exist_ok=True)
                with open(self.LEDGER, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            except Exception as e:
                return {"status": "REGISTER_FAILED", "error": str(e)[:120]}
        return {"status": "HYPOTHESIS_REGISTERED", "name": name}

    def record_verdict(self, name, verdict, effect_pct=None, p_value=None,
                       horizon_days=None, detail=None, save=True):
        """Record the outcome — nulls included. Omitting nulls is how a search lies."""
        rec = {
            "name": name, "verdict": verdict, "recorded_at": datetime.utcnow().isoformat(),
            "effect_pct": effect_pct, "p_value": p_value, "horizon_days": horizon_days,
            "detail": detail, "is_verdict": True,
        }
        if save:
            try:
                self.LEDGER.parent.mkdir(parents=True, exist_ok=True)
                with open(self.LEDGER, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            except Exception as e:
                return {"status": "VERDICT_WRITE_FAILED", "error": str(e)[:120]}
        return {"status": "VERDICT_RECORDED", "name": name, "verdict": verdict}

    def family_wise_threshold(self):
        """The p-value a NEW result must beat, given everything already tested."""
        tested = [r for r in self._read() if r.get("is_verdict")]
        n = max(1, len(tested))
        return {
            "hypotheses_tested": n,
            "naive_threshold": 0.05,
            "family_wise_threshold": round(0.05 / n, 5),
            "note": ("Bonferroni across the WHOLE search, not just the current study. Testing "
                     "many hypotheses at 0.05 guarantees false positives; the bar rises with "
                     "every hypothesis ever tried."),
        }

    def status(self):
        rows = self._read()
        verdicts = [r for r in rows if r.get("is_verdict")]
        by_verdict = {}
        for v in verdicts:
            by_verdict[str(v.get("verdict"))] = by_verdict.get(str(v.get("verdict")), 0) + 1
        survivors = [v for v in verdicts
                     if str(v.get("verdict", "")).upper().startswith(("EDGE", "CANDIDATE"))]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "hypotheses_registered": len([r for r in rows if not r.get("is_verdict")]),
            "hypotheses_tested": len(verdicts),
            "verdict_counts": by_verdict,
            "surviving_candidates": [v.get("name") for v in survivors],
            "threshold": self.family_wise_threshold(),
            "screens": {
                "1_economic_magnitude": (f"effect must exceed {self.OPTION_ROUNDTRIP_COST_BPS}bps "
                                         f"x{self.REQUIRED_MULTIPLE} to be viable as OTM options; "
                                         f"{self.DELTA1_ROUNDTRIP_COST_BPS}bps x"
                                         f"{self.REQUIRED_MULTIPLE} as delta-1"),
                "2_statistical": "family-wise corrected across every hypothesis ever tested",
            },
            "status": "EDGE_REGISTRY_READY",
        }
