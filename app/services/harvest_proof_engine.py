"""Prove (or disprove) the variance-premium harvest from REAL closed trades — not backtests.

The grade's one conditionally-fixable weakness is "unproven edge": the harvest is real in theory but
has zero demonstrated live P&L. Data can't manufacture the edge, but it CAN measure it — and that only
works if every trade records the conditions it was sold under. The VRP ledger now carries that
provenance at entry (entry_iv_rank, entry_dte, dte_selection_mode, entry_skew) and the outcome at exit
(realized_pnl, close_reason). This engine reads those closed units and reports, honestly:

  * did the harvest actually pay?            — total realized P&L, win rate, credit capture, RoR
  * is the richness condition earning it?    — outcomes bucketed by entry IV-rank (the 9.6x thesis)
  * does adaptive tenor beat static?         — outcomes split by dte_selection_mode
  * how did positions leave?                 — by close_reason (profit-take vs stop vs manage-DTE)

It computes NOTHING from a model and predicts NOTHING. It is a mirror on realized results, and it
refuses to claim significance it doesn't have: below MIN_FOR_SIGNAL closed trades every split is
labelled UNDERPOWERED. This is the apparatus that can move the edge grade from D — but only months of
real, honestly-counted trades can actually move it.
"""

import json
import statistics
from datetime import datetime
from pathlib import Path


class HarvestProofEngine:

    LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
    MIN_FOR_SIGNAL = 20          # below this, any split is honestly too small to read
    RICH_SPLIT = 0.80            # entry IV-rank bucket boundary (rich vs richest tercile+)

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _rows(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    @staticmethod
    def _hold_days(r):
        try:
            o = datetime.fromisoformat(str(r.get("opened_at")))
            c = datetime.fromisoformat(str(r.get("closed_at")))
            return max(0.0, (c - o).total_seconds() / 86400.0)
        except Exception:
            return None

    def _agg(self, rows):
        """Summary stats over a set of closed units."""
        n = len(rows)
        if not n:
            return {"n": 0}
        pnl = [self._f(r.get("realized_pnl")) or 0.0 for r in rows]
        caps = [(self._f(r.get("realized_pnl")) / self._f(r.get("credit_total")))
                for r in rows if self._f(r.get("credit_total"))]
        rors = [(self._f(r.get("realized_pnl")) / self._f(r.get("max_loss_total")))
                for r in rows if self._f(r.get("max_loss_total"))]
        dtes = [self._f(r.get("entry_dte")) for r in rows if self._f(r.get("entry_dte")) is not None]
        holds = [h for h in (self._hold_days(r) for r in rows) if h is not None]
        wins = sum(1 for x in pnl if x > 0)
        return {
            "n": n,
            "total_realized_pnl": round(sum(pnl), 2),
            "win_rate": round(wins / n, 3),
            "avg_credit_capture": round(statistics.mean(caps), 3) if caps else None,
            "avg_return_on_risk": round(statistics.mean(rors), 3) if rors else None,
            "avg_entry_dte": round(statistics.mean(dtes), 1) if dtes else None,
            "avg_hold_days": round(statistics.mean(holds), 1) if holds else None,
            "underpowered": n < self.MIN_FOR_SIGNAL,
        }

    def status(self):
        rows = self._rows()
        closed = [r for r in rows if str(r.get("status")).upper() == "CLOSED"]
        opens = [r for r in rows if str(r.get("status")).upper() == "OPEN"]

        overall = self._agg(closed)

        # by tenor-selection mode — the adaptive-vs-static comparison
        by_mode = {}
        for mode in ("adaptive", "static"):
            grp = [r for r in closed if str(r.get("dte_selection_mode")) == mode]
            if grp:
                by_mode[mode] = self._agg(grp)

        # by STRATEGY — the index-VRP harvest vs the earnings-vol probe, kept separate so each is
        # attributable on its own merits (they answer different edge questions).
        by_strategy = {}
        for strat in sorted({str(r.get("strategy") or "vrp_index") for r in closed}):
            grp = [r for r in closed if str(r.get("strategy") or "vrp_index") == strat]
            if grp:
                by_strategy[strat] = self._agg(grp)

        # by entry richness — is the rich-IV condition (the 9.6x thesis) actually earning it?
        rich = [r for r in closed if (self._f(r.get("entry_iv_rank")) or 0) < self.RICH_SPLIT]
        richest = [r for r in closed if (self._f(r.get("entry_iv_rank")) or 0) >= self.RICH_SPLIT]
        by_richness = {}
        if rich:
            by_richness[f"iv_rank_0.67-{self.RICH_SPLIT}"] = self._agg(rich)
        if richest:
            by_richness[f"iv_rank_>={self.RICH_SPLIT}"] = self._agg(richest)

        # by exit reason
        by_reason = {}
        for r in closed:
            k = str(r.get("close_reason") or "UNKNOWN")
            b = by_reason.setdefault(k, {"n": 0, "pnl": 0.0})
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + (self._f(r.get("realized_pnl")) or 0.0), 2)

        n = overall.get("n", 0)
        if n == 0:
            verdict = ("NO CLOSED TRADES YET — the harvest is armed and now records full entry "
                       "provenance, so proof will accrue from the first close. Nothing to conclude.")
        elif n < self.MIN_FOR_SIGNAL:
            verdict = (f"UNDERPOWERED — {n}/{self.MIN_FOR_SIGNAL} closed trades. Real P&L is shown but "
                       "no split (adaptive vs static, rich vs richest) can be trusted yet; correlated, "
                       "small sample. Do NOT scale on this.")
        else:
            verdict = (f"READABLE — {n} closed trades. Splits below are directional evidence, still not "
                       "proof through a real vol regime; the tail is the part a calm sample can't price.")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "closed_trades": n,
            "open_positions": len(opens),
            "open_deployed_risk_usd": round(sum(self._f(r.get("max_loss_total")) or 0.0 for r in opens), 2),
            "overall": overall,
            "by_strategy": by_strategy or {"note": "no closed trades yet"},
            "by_dte_selection_mode": by_mode or {"note": "no closed trades tagged with a mode yet"},
            "by_entry_richness": by_richness or {"note": "no closed trades yet"},
            "by_close_reason": by_reason or {"note": "no closed trades yet"},
            "verdict": verdict,
            "honest_note": ("this measures REALIZED trades only — it manufactures no edge and forecasts "
                            "nothing. A positive read here is necessary but not sufficient: the variance "
                            "premium is a crash premium, so a calm-sample win rate is expected and does "
                            "not prove the tail is survivable. Only months including a real vol event can."),
            "status": "HARVEST_PROOF_STATUS",
        }
