from datetime import datetime
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore
from app.services.fixed_horizon_grader_engine import FixedHorizonGraderEngine
from app.services.continuity_monitor_engine import ContinuityMonitorEngine


class DataIntegrityEngine:
    """
    Is the ground-truth data GreyLine learns from actually trustworthy?

    The learning loop only compounds if its inputs are clean. This report answers the
    questions that decide whether accumulating more data helps or just grows a poisoned
    well, and it names the failures we have already been burned by:

      * Independence — the same market moment re-recorded many times looks like many
        independent trials but is one. Duplication factor and distinct days expose it.
      * Completeness — how much is actually graded vs still maturing (PENDING).
      * Balance — a lopsided label mix warns that a regime or direction dominates.
      * Forward-price coverage — fixed-horizon grading is impossible without prices
        recorded as the market moves forward. Confirms the feed is alive and growing.
      * Skill — the drift-robust read (Matthews correlation), so a spurious hit rate
        can't masquerade as edge.

    Read-only. Verdict is GREEN / AMBER / RED with the specific reasons.
    """

    GRADES = Path("app/data/forecast_outcome_grades.jsonl")
    OUTCOME_LEDGER = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")

    # A regime/day needs enough INDEPENDENT evidence before its stats mean anything.
    MIN_DISTINCT_DAYS = 5
    # Above this, records are mostly re-recordings of the same moments, not new evidence.
    MAX_HEALTHY_DUPLICATION = 1.5

    def _moment(self, row):
        return (row.get("symbol"), row.get("snapshot_price"))

    def _day(self, row):
        ts = str(
            row.get("candidate_timestamp")
            or row.get("forecast_timestamp")
            or row.get("timestamp")
            or ""
        )
        return ts[:10] or None

    def diagnose(self):
        grades = read_jsonl(self.GRADES)
        ledger = read_jsonl(self.OUTCOME_LEDGER)

        reasons = []

        # --- independence ---
        graded = [r for r in grades if r.get("forecast_correct") is not None]
        moments = {self._moment(r) for r in graded}
        days = {d for d in (self._day(r) for r in graded) if d}
        distinct_days = len(days)
        distinct_moments = len(moments)
        duplication = round(len(graded) / distinct_moments, 2) if distinct_moments else 0.0

        if distinct_days < self.MIN_DISTINCT_DAYS:
            reasons.append(
                f"Only {distinct_days} distinct day(s) of graded data "
                f"(need >= {self.MIN_DISTINCT_DAYS} before regime edge is trustworthy)."
            )
        if duplication > self.MAX_HEALTHY_DUPLICATION:
            reasons.append(
                f"Duplication factor {duplication}x: {len(graded)} records cover only "
                f"{distinct_moments} distinct market moments — evidence is over-counted."
            )

        # --- balance ---
        bull = sum(1 for r in graded if str(r.get("predicted_direction")).upper() == "BULLISH")
        bear = sum(1 for r in graded if str(r.get("predicted_direction")).upper() == "BEARISH")
        directional = bull + bear
        bull_pct = round(100 * bull / directional, 1) if directional else 0.0
        if directional and (bull_pct < 20 or bull_pct > 80):
            reasons.append(
                f"Label imbalance: {bull_pct}% bullish — one direction dominates, "
                f"so accuracy is easy to fake by following the tape."
            )

        # --- forward-price coverage (the fuel for fixed-horizon grading) ---
        store = PriceHistoryStore()
        symbols = sorted({r.get("symbol") for r in ledger if r.get("symbol")})
        covered = 0
        total_points = 0
        spans_hours = []
        for sym in symbols:
            cov = store.coverage(sym)
            pts = cov.get("points") or 0
            total_points += pts
            if pts >= 2:
                covered += 1
                first, last = cov.get("first"), cov.get("last")
                if first and last:
                    try:
                        dh = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 3600
                        spans_hours.append(dh)
                    except Exception:
                        pass
        coverage_pct = round(100 * covered / len(symbols), 1) if symbols else 0.0
        max_span_h = round(max(spans_hours), 1) if spans_hours else 0.0

        if coverage_pct < 50:
            reasons.append(
                f"Forward-price coverage {coverage_pct}%: most forecast symbols have no "
                f"accumulating price series, so fixed-horizon grading can't mature."
            )

        # --- drift-robust skill ---
        fh = FixedHorizonGraderEngine().grade()
        counts = fh.get("counts", {})
        pending = counts.get("PENDING_NO_FORWARD_PRICE", 0)
        decisive = fh.get("graded_count", 0)
        mcc = (fh.get("skill") or {}).get("mcc")

        if decisive == 0:
            reasons.append(
                "Fixed-horizon grader has 0 matured decisions — no forward prices near "
                "T+horizon yet. Edge is unmeasurable until the price feed accumulates."
            )

        # --- continuity (a gap means the data has holes, not that markets were quiet) ---
        continuity = ContinuityMonitorEngine().diagnose()
        if continuity.get("verdict") == "RED":
            reasons.append(f"Continuity: {continuity.get('headline')}")
        elif continuity.get("verdict") == "AMBER":
            reasons.append(
                f"Continuity: {continuity.get('gap_count')} accumulation gap(s), "
                f"largest {continuity.get('largest_gap_minutes')} min — that data is missing, not quiet."
            )

        # --- verdict ---
        if any("distinct day" in r or "0 matured" in r or "coverage" in r
               or "STALLED" in r for r in reasons):
            verdict = "RED"
            headline = "Data is not yet trustworthy enough to draw conclusions from."
        elif reasons:
            verdict = "AMBER"
            headline = "Data is usable but has integrity gaps to watch as it grows."
        else:
            verdict = "GREEN"
            headline = "Ground-truth data passes independence, balance, and coverage checks."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "DATA_INTEGRITY",
            "verdict": verdict,
            "headline": headline,
            "reasons": reasons or ["No integrity issues detected."],
            "independence": {
                "graded_records": len(graded),
                "distinct_market_moments": distinct_moments,
                "distinct_days": distinct_days,
                "duplication_factor": duplication,
                "min_distinct_days_required": self.MIN_DISTINCT_DAYS,
            },
            "label_balance": {
                "bullish": bull, "bearish": bear, "bullish_pct": bull_pct,
            },
            "forward_price_coverage": {
                "symbols_tracked": len(symbols),
                "symbols_with_series": covered,
                "coverage_pct": coverage_pct,
                "total_points": total_points,
                "max_span_hours": max_span_h,
            },
            "fixed_horizon_skill": {
                "horizon_hours": fh.get("horizon_hours"),
                "matured_decisions": decisive,
                "pending": pending,
                "balanced_accuracy": fh.get("balanced_accuracy_precision_based"),
                "mcc": mcc,
                "note": "MCC > 0 (significant) = real directional skill; ~0 = none; < 0 = anti-skill.",
            },
            "continuity": {
                "verdict": continuity.get("verdict"),
                "currently_live": continuity.get("currently_live"),
                "uptime_pct": continuity.get("uptime_pct"),
                "gap_count": continuity.get("gap_count"),
                "largest_gap_minutes": continuity.get("largest_gap_minutes"),
            },
            "status": "DATA_INTEGRITY_READY",
        }
