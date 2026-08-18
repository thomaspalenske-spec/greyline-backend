"""Forward-shadow VRP proof — a RIGOROUS forward-test verdict on the confirmed variance-premium edge,
accruing far faster than the capital-limited live book.

THE PROBLEM: the live VRP sleeve opens only 1-2 condors at a time on the $10k book, each 28-56 DTE, so it
produces ~1-2 closes/month — 20 day-clustered closes (the court's verdict gate) is roughly a YEAR away
(/edge-persistence/proof-maturity: premium_vrp 0/20). That is the single slowest thing gating the grade.

THE FIX: the zero-capital condor SHADOW (condor_shadow_engine) already forward-tests the SAME VRP across
many underlyings every cycle and SETTLES condors at profit-take / near-expiry — with real UW mid prices,
out-of-sample, post-registration. This engine feeds those settled shadow closes into the court's RIGOROUS
statistics — the SAME day-clustered, cost-net, small-sample-t 95% CI bar a live sleeve must clear
(EdgePersistenceEngine.verdict_from_returns) — to answer "does the VRP edge hold FORWARD?" on a far shorter
clock than the live book.

HONEST LABEL: this is a FORWARD-TEST verdict (zero-capital, mid-marked, no real fills), NOT the grade's
"PROVEN LIVE" standard. It cannot flip Edge D+ -> B by itself. What it DOES: give the fastest trustworthy
read on whether the backtest-confirmed edge survives forward — the evidence that informs the fund/scale
decision (funding then accelerates the live proof too)."""

from datetime import date, datetime


class CondorShadowProofEngine:

    MIN_DAYS = 20                                    # same day-clustered gate as the live court
    VRP_SLEEVES = ("vrp", "index_vrp", "commodity_vrp")   # the variance-premium family (earnings is separate/retired)

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _closed(self):
        import json
        try:
            from app.services.condor_shadow_engine import LEDGER
            rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []
        return [r for r in rows if r.get("status") == "CLOSED"]

    def _close_cost(self, e):
        """REALISTIC round-trip close cost in $ from the condor's own stored NBBO — the half-spread per leg
        (mark is at MID; closing crosses to the touch) summed over the 4 legs x100 x qty. This is the honest
        cost, not a flat 3%-of-max-loss haircut: single-name option spreads run 5-10x wider than index
        options, so a flat haircut FLATTERS single-name condors. Returns (cost_usd, had_spreads)."""
        legs = (e.get("legs") or {}).values()
        qty = int(self._f(e.get("quantity")) or 0)
        half, seen = 0.0, 0
        for l in legs:
            b, a = self._f(l.get("bid")), self._f(l.get("ask"))
            if a > 0 and a >= b:
                half += (a - b) / 2.0
                seen += 1
        return half * 100.0 * qty, seen >= 3

    def _eligible(self, e):
        """Does the LIVE sleeve actually TRADE this underlying? The single-name 'vrp' sleeve is ETF-only by
        default (single-name condors were RETIRED as cost-eaten — GREYLINE_VRP_ETF_ONLY), so legacy
        single-name shadow condors (opened before the cutover) must NOT pollute the forward verdict for a
        strategy the live book will never run. index_vrp / commodity_vrp trade their own roots — untouched."""
        if e.get("sleeve") != "vrp":
            return True
        try:
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
            if V._vrp_etf_only():
                return str(e.get("symbol") or "").upper() in set(V.LIQUID_ETFS)
        except Exception:
            pass
        return True

    def _day_returns(self, closed, sleeves):
        """Day-clustered, cost-net return-on-risk observations. INDEPENDENCE by day: condors closed on the
        same date are ONE observation (sum net / sum risk) — the same anti-inflation clustering the live
        court uses. Cost is the condor's OWN measured round-trip spread (falls back to the court's flat
        haircut only when a condor stored no usable NBBO)."""
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        hc = EP.CONDOR_CLOSE_HAIRCUT_FRAC
        by_day, rows, excluded = {}, 0, 0
        for e in closed:
            if e.get("sleeve") not in sleeves:
                continue
            if not self._eligible(e):          # retired single-name condor — not what the live sleeve trades
                excluded += 1
                continue
            qty = int(self._f(e.get("quantity")) or 0)
            risk = self._f(e.get("max_loss_per")) * qty
            if risk <= 0:
                continue
            cost, had = self._close_cost(e)
            if not had:
                cost = hc * risk                                   # fallback: flat haircut on a data gap
            net = self._f(e.get("realized_pnl")) - cost            # cost-net at the REAL spread
            d = str(e.get("closed_date") or "")[:10]
            if not d:
                continue
            sn, sr = by_day.get(d, (0.0, 0.0))
            by_day[d] = (sn + net, sr + risk)
            rows += 1
        days = [(d, sn / sr) for d, (sn, sr) in sorted(by_day.items()) if sr > 0]
        return days, rows, excluded

    def cost_validation(self):
        """Measured condor round-trip close cost (as %-of-max-loss) vs the court's flat 3% haircut — the
        honesty check on whether the shadow's mid-marked returns are realistically costed. A big gap means
        the flat haircut flatters (single-name) condors."""
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        fracs = {}
        for e in self._closed():
            qty = int(self._f(e.get("quantity")) or 0)
            risk = self._f(e.get("max_loss_per")) * qty
            cost, had = self._close_cost(e)
            if risk > 0 and had:
                fracs.setdefault(e.get("sleeve"), []).append(cost / risk)
        def _stat(xs):
            xs = sorted(xs)
            n = len(xs)
            return None if not n else {"n": n, "median_pct": round(xs[n // 2] * 100, 1),
                                       "mean_pct": round(sum(xs) / n * 100, 1),
                                       "max_pct": round(xs[-1] * 100, 1)}
        return {"court_flat_haircut_pct": round(EP.CONDOR_CLOSE_HAIRCUT_FRAC * 100, 1),
                "measured_by_sleeve": {k: _stat(v) for k, v in fracs.items()},
                "note": ("Real round-trip close cost = half the 4-leg NBBO spread / max-loss. Single-name "
                         "condor spreads dwarf the flat 3% haircut; index (XSP) spreads are far tighter — "
                         "which is why the CONFIRMED edge is index VRP, not single-name.")}

    def _track(self, sleeves, label):
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        days, rows, excluded = self._day_returns(self._closed(), sleeves)
        v = EP.verdict_from_returns([r for _, r in days], min_n=self.MIN_DAYS)
        eta = None
        if 2 <= len(days) < self.MIN_DAYS:
            try:
                span = (date.fromisoformat(days[-1][0]) - date.fromisoformat(days[0][0])).days or 1
                rate = len(days) / span                            # observations per calendar day
                if rate > 0:
                    eta = round((self.MIN_DAYS - len(days)) / rate)
            except Exception:
                pass
        v.update({
            "track": "FORWARD_SHADOW (out-of-sample, zero-capital, mid-marked — NOT live-proven)",
            "label": label, "sleeves": list(sleeves),
            "independent_days": len(days), "closed_condor_rows": rows,
            "excluded_ineligible_rows": excluded,     # retired single-name condors the live sleeve won't trade
            "first_close": days[0][0] if days else None, "last_close": days[-1][0] if days else None,
            "eta_days_to_verdict": eta,
        })
        return v

    def report(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "vrp_family": self._track(self.VRP_SLEEVES, "VRP variance-premium (forward shadow)"),
            "by_sleeve": {s: self._track((s,), s) for s in self.VRP_SLEEVES},
            "cost_validation": self.cost_validation(),
            "note": ("Forward-test verdict on the confirmed VRP edge from the zero-capital condor shadow, "
                     "judged on the LIVE court's bar (day-clustered, cost-net, 95% CI, 20-day gate). Accrues "
                     "faster than the capital-limited live book. FORWARD-TEST, not live-proven — it informs "
                     "the fund/scale decision; it does not by itself flip the Edge grade."),
            "status": "CONDOR_SHADOW_PROOF",
        }
