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

    def _day_returns(self, closed, sleeves):
        """Day-clustered, cost-net return-on-risk observations for the given sleeves. INDEPENDENCE by day:
        condors closed on the same date are ONE observation (sum net / sum risk) — the same anti-inflation
        clustering the live court uses. Cost: the court's condor MID-close haircut (a round-trip spread
        proxy), so the shadow is judged net of realistic close costs, not on a free mid."""
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        hc = EP.CONDOR_CLOSE_HAIRCUT_FRAC
        by_day, rows = {}, 0
        for e in closed:
            if e.get("sleeve") not in sleeves:
                continue
            qty = int(self._f(e.get("quantity")) or 0)
            risk = self._f(e.get("max_loss_per")) * qty
            if risk <= 0:
                continue
            net = self._f(e.get("realized_pnl")) - hc * risk       # cost-net, same treatment as live court
            d = str(e.get("closed_date") or "")[:10]
            if not d:
                continue
            sn, sr = by_day.get(d, (0.0, 0.0))
            by_day[d] = (sn + net, sr + risk)
            rows += 1
        days = [(d, sn / sr) for d, (sn, sr) in sorted(by_day.items()) if sr > 0]
        return days, rows

    def _track(self, sleeves, label):
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        days, rows = self._day_returns(self._closed(), sleeves)
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
            "first_close": days[0][0] if days else None, "last_close": days[-1][0] if days else None,
            "eta_days_to_verdict": eta,
        })
        return v

    def report(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "vrp_family": self._track(self.VRP_SLEEVES, "VRP variance-premium (forward shadow)"),
            "by_sleeve": {s: self._track((s,), s) for s in self.VRP_SLEEVES},
            "note": ("Forward-test verdict on the confirmed VRP edge from the zero-capital condor shadow, "
                     "judged on the LIVE court's bar (day-clustered, cost-net, 95% CI, 20-day gate). Accrues "
                     "faster than the capital-limited live book. FORWARD-TEST, not live-proven — it informs "
                     "the fund/scale decision; it does not by itself flip the Edge grade."),
            "status": "CONDOR_SHADOW_PROOF",
        }
