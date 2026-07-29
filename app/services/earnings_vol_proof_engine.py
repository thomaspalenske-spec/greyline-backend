"""Is the earnings implied move systematically overpriced? Read the forward panel, honestly.

The earnings IV-crush edge CANNOT be backtested (UW's historic-contract endpoint returns zero rows;
TradeStation purges expired contracts — verified). The ONLY honest measure is the forward panel
(EarningsVolEdgeEngine): record each earnings' IMPLIED move before the announcement, resolve the
REALIZED move after, pair them. spread = implied - realized; a systematically POSITIVE spread means
the options overpriced the move -> selling defined-risk premium into earnings pays.

This engine reports that edge as it accrues — and refuses to claim significance it doesn't have.
Below MIN_FOR_SIGNAL resolved events every read is labelled UNDERPOWERED, and it states plainly that
a spread measured over a calm sample does not price the gap-risk tail. Panel started 2026-07-24;
expect a first directional read in ~1-2 months, real power in ~6-12.
"""

import json
import statistics
from datetime import datetime
from pathlib import Path


class EarningsVolProofEngine:

    PANEL = Path("app/data/research/earnings_vol_panel.jsonl")
    MIN_FOR_SIGNAL = 30          # resolved earnings events before any split can be trusted
    RICH_SPLIT = 0.80            # iv_rank bucket boundary

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _rows(self):
        try:
            return [json.loads(l) for l in self.PANEL.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def _agg(self, resolved):
        spreads = [self._f(r.get("spread_pct")) for r in resolved]
        spreads = [s for s in spreads if s is not None]
        n = len(spreads)
        if not n:
            return {"n": 0}
        overpriced = sum(1 for s in spreads if s > 0)      # implied > realized (selling would pay)
        return {
            "n": n,
            "mean_spread_pct": round(statistics.mean(spreads), 3),      # + = options overpriced the move
            "median_spread_pct": round(statistics.median(spreads), 3),
            "overpriced_rate": round(overpriced / n, 3),               # fraction where implied > realized
            "stdev_spread_pct": round(statistics.pstdev(spreads), 3) if n > 1 else None,
            "underpowered": n < self.MIN_FOR_SIGNAL,
        }

    def status(self):
        rows = self._rows()
        implied = [r for r in rows if r.get("kind") == "implied"]
        resolved = [r for r in rows if r.get("kind") == "resolved"]

        overall = self._agg(resolved)
        rich = [r for r in resolved if (self._f(r.get("iv_rank")) or 0) < self.RICH_SPLIT]
        richest = [r for r in resolved if (self._f(r.get("iv_rank")) or 0) >= self.RICH_SPLIT]
        by_richness = {}
        if rich:
            by_richness[f"iv_rank_<{self.RICH_SPLIT}"] = self._agg(rich)
        if richest:
            by_richness[f"iv_rank_>={self.RICH_SPLIT}"] = self._agg(richest)

        n = overall.get("n", 0)
        first = min((str(r.get("recorded_at") or "")[:10] for r in implied), default=None)
        if n == 0:
            verdict = (f"ACCRUING — {len(implied)} implied moves captured, 0 resolved yet (earnings "
                       "haven't reported / windows haven't closed). No edge to read. This is the only "
                       "honest measure; a backtest is impossible (no historical options data exists).")
        elif n < self.MIN_FOR_SIGNAL:
            verdict = (f"UNDERPOWERED — {n}/{self.MIN_FOR_SIGNAL} resolved. A positive mean_spread hints "
                       "options overprice earnings moves, but the sample is tiny and correlated. Do NOT "
                       "trade size on this.")
        else:
            mean = overall.get("mean_spread_pct")
            lean = "options OVERPRICE the move (selling premium leans positive)" if (mean or 0) > 0 \
                else "options UNDERprice the move (selling would lean negative)"
            verdict = (f"READABLE — {n} resolved. mean spread {mean}pp => {lean}. Still NOT proof through "
                       "a real vol regime: a calm-sample spread does not price the earnings gap tail.")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "panel_started": first,
            "implied_captured": len(implied),
            "resolved_events": n,
            "edge_definition": "spread = implied_move - realized_move (percentage points); "
                               "positive & persistent => selling defined-risk earnings premium pays",
            "overall": overall,
            "by_entry_richness": by_richness or {"note": "no resolved events yet"},
            "verdict": verdict,
            "honest_note": ("measures the PANEL edge only (implied vs realized move), unbiased by "
                            "execution. Whether GreyLine can CAPTURE it net of spread+fees is a "
                            "separate question answered by the traded earnings-vol condors on "
                            "/harvest-proof. Backtest is impossible; this accrues forward from 2026-07-24."),
            "status": "EARNINGS_VOL_PROOF_STATUS",
        }
