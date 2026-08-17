"""First real (strategy-logic) close watch — pages the operator the moment ANY sleeve books its first
NON-FORCED exit, so the edge-proof accumulation (n toward each sleeve's required_n) actually starts
being tracked instead of sitting at zero.

Context: as of 2026-08-04 GreyLine has NEVER closed a single trade on its own strategy logic — every
one of its ~7 historical closes was a FORCED flatten (clean-slate resets / rebaselines), which the edge
court correctly EXCLUDES. So the court reads ACCUMULATING (n=0) for every sleeve and Edge is stuck at
D+ for lack of evidence, not for lack of a proven strategy. The one thing that moves Edge is the FIRST
real closed trade — and it is easy to miss when it finally happens. This watch makes it unmissable.

It does NOT recompute anything: it reads EdgePersistenceEngine.realized_edge() (the authoritative
fill-truthful court, which already excludes forced closes) and detects when a sleeve transitions from
0 -> >=1 valid closed trades. Fires a ONE-TIME iMessage per sleeve (permanent marker — never re-pages),
and a distinct one-time 'first ever, any sleeve' milestone. Read-only on the trading path.
"""

import json
from datetime import datetime
from pathlib import Path


class EdgeFirstCloseWatchEngine:

    STATE = Path("app/data/state/edge_first_close_seen.json")
    # RETIRED sleeves are NOT being proven — their closes must not trigger the milestone. The condor
    # sleeves are retired because the SIM mis-prices atomic multi-leg closes, so their "closes" are
    # exactly the un-trustworthy ones; a POST_EARNINGS_EXIT on them is not the real-edge milestone we
    # watch for. Remove a sleeve here if/when it is re-armed. See greyline-edge-proof-protocol.
    RETIRED_SLEEVES = {"premium_vrp", "premium_earnings"}

    def _load_seen(self):
        try:
            d = json.loads(self.STATE.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save_seen(self, seen):
        try:
            self.STATE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps(seen, indent=2))
        except Exception:
            pass

    def _court_sleeves(self):
        """{sleeve: {trades, total_net_pnl, mean_return_on_risk_pct, verdict}} for sleeves with >=1 valid
        (non-forced) closed trade — read straight from the authoritative court, never recomputed."""
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        edge = EdgePersistenceEngine().realized_edge()
        out = {}
        for sleeve, s in (edge.get("sleeves") or {}).items():
            if sleeve in self.RETIRED_SLEEVES:
                continue
            if int(s.get("trades") or 0) >= 1:
                out[sleeve] = {"trades": s.get("trades"), "total_net_pnl": s.get("total_net_pnl"),
                               "mean_return_on_risk_pct": s.get("mean_return_on_risk_pct"),
                               "verdict": s.get("verdict")}
        return out

    def evaluate(self):
        """PURE (no paging, no mutation): compare the court's sleeves-with-closes to what we've already
        recorded. Returns the seen set, sleeves newly crossing 0->first-close, and those still awaiting."""
        seen = self._load_seen()
        current = self._court_sleeves()
        newly = {s: v for s, v in current.items() if s not in seen}
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "any_real_close_ever": bool(seen) or bool(current),
            "sleeves_with_first_close": sorted(set(seen) | set(current)),
            "newly_first_closed": newly,
            "already_recorded": sorted(seen),
            "status": "EDGE_FIRST_CLOSE_EVAL",
        }

    def run_cycle(self):
        """Detect NEW first-closes, page each once (permanent marker), and record them. Idempotent: a
        sleeve already in the marker is never re-paged. Safe to call every scheduler cycle."""
        seen = self._load_seen()
        current = self._court_sleeves()
        newly = {s: v for s, v in current.items() if s not in seen}
        if not newly:
            return {"status": "EDGE_FIRST_CLOSE_NONE_NEW", "paged": [],
                    "already_recorded": sorted(seen)}

        first_ever = not seen                              # is this the FIRST real close in GreyLine's life?
        from app.services.external_alert_engine import ExternalAlertEngine
        alerter = ExternalAlertEngine()
        paged = []
        for sleeve, v in sorted(newly.items()):
            net = v.get("total_net_pnl")
            ror = v.get("mean_return_on_risk_pct")
            lead = "🎯 FIRST REAL CLOSE — GreyLine's FIRST-EVER strategy-logic exit" if (first_ever and not paged) \
                else "🎯 First real close for a sleeve"
            msg = (f"{lead}. Sleeve '{sleeve}' booked its first NON-FORCED exit: "
                   f"net {'$%.2f' % net if isinstance(net, (int, float)) else net}, "
                   f"return-on-risk {ror}%. The edge court is now accumulating real evidence "
                   f"({v.get('verdict')}). Every prior close was a forced flatten — this is the first "
                   f"the apparatus will count.")
            res = alerter.dispatch("GreyLine: first real close", msg, severity="INFO",
                                   fingerprint=f"edge_first_close:{sleeve}")
            seen[sleeve] = {"recorded_at": datetime.utcnow().isoformat(),
                            "trades_at_detection": v.get("trades"),
                            "total_net_pnl": net, "verdict": v.get("verdict"),
                            "was_first_ever": bool(first_ever and not paged),
                            "alert_status": res.get("status")}
            paged.append({"sleeve": sleeve, "alert_status": res.get("status"),
                          "reached_off_machine": res.get("reached_off_machine")})
        self._save_seen(seen)
        return {"status": "EDGE_FIRST_CLOSE_PAGED", "paged": paged,
                "first_ever_milestone": first_ever, "already_recorded": sorted(seen)}

    def status(self):
        ev = self.evaluate()
        ev["status"] = "EDGE_FIRST_CLOSE_STATUS"
        ev["note"] = ("Watches the edge court for the first NON-FORCED close per sleeve; pages iMessage "
                      "once per sleeve. Until any sleeve appears here, Edge stays ACCUMULATING (n=0) "
                      "because every historical close was a forced flatten.")
        return ev
