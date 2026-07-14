import json
from datetime import datetime
from pathlib import Path


class FlatDayDiagnosticsEngine:
    """
    Answers one operator question loudly: "Am I flat, and if so, WHY?"

    Scans the most recent master-decision cycles and reports whether the system is
    producing executions. If it is flat, it distinguishes the two cases that look
    identical from the outside but mean opposite things:

      * FLAT_WITH_SUPPRESSED_SIGNAL - candidates DID meet EXECUTE thresholds but were
        demoted by a gate. This is the dangerous case: a real, actionable signal was
        thrown away. The dominant demoting gate is named.
      * FLAT_NO_QUALIFIED_SIGNAL - nothing met EXECUTE thresholds. Flat here is
        legitimate discipline, not a bug.

    Built after the 2026-07-13 zero-trade session, where 3,929 EXECUTE-qualified bearish
    puts were silently demoted by a bull-biased regime gate and nobody knew until after
    the close. This turns that failure mode into a pre-open / intraday alarm.
    """

    EVENTS = Path("app/data/master_decisions/master_decision_events.jsonl")
    COMPOSITE_EXECUTE_MIN = 85
    DIRECTION_CONFIDENCE_MIN = 5

    def __init__(self, lookback_cycles=300):
        self.lookback_cycles = max(1, int(lookback_cycles))

    def _tail(self, path, n):
        """Return the last n parsed JSON rows without loading the whole file."""
        if not path.exists():
            return []
        with open(path, "rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            buf = b""
            block = 8192
            while pos > 0 and buf.count(b"\n") <= n:
                read = min(block, pos)
                pos -= read
                f.seek(pos)
                buf = f.read(read) + buf
        rows = []
        for line in buf.splitlines()[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (ValueError, TypeError):
                continue
        return rows

    @staticmethod
    def _attribute(tc, event=None):
        """Name the gate that stopped an EXECUTE-qualified candidate from trading."""
        event = event or {}

        # The candidate cleared scoring as EXECUTE but the master decision still
        # refused it, so the kill came from the decision layer (risk / exposure /
        # broker), not from a scoring demotion. Attribute to the decision reason.
        if tc.get("result") == "EXECUTE":
            reason = (event.get("decision_reason") or "").upper()
            if "MAX_SECTOR_EXPOSURE_PCT" in reason:
                return "EXPOSURE_LIMIT_GATE_SECTOR_CONCENTRATION"
            if "MAX_OPEN_POSITIONS" in reason:
                return "EXPOSURE_LIMIT_GATE_MAX_OPEN_POSITIONS"
            if "LIMIT_BREACH" in reason:
                return "EXPOSURE_LIMIT_GATE"
            if "RISK" in reason:
                return "RISK_STATE_GATE_DECISION_LAYER"
            if "BROKER" in reason:
                return "BROKER_READINESS_GATE"
            return "DECISION_LAYER_BLOCK"

        # Explicit fields (present on records written after the 07-13 fix).
        if tc.get("directional_regime_weak") is True:
            return "REGIME_GATE_WEAK_DIRECTIONAL"
        if tc.get("risk_state") in ("DEFENSIVE", "STRESSED"):
            return "RISK_STATE_GATE"
        if tc.get("institutional_flow_gate") == "MISALIGNED_DOWNGRADED":
            return "FLOW_MISALIGNMENT_GATE"
        if tc.get("regime_execution_allowed") is False:
            return "REGIME_CALIBRATION_NEGATIVE_EDGE"
        # Legacy inference for older records that lack the directional fields.
        if tc.get("regime") == "WEAK_LIVE":
            return "REGIME_GATE_WEAK_LIVE_LEGACY"
        return "OTHER_OR_FLOW_DECAY"

    def diagnose(self):
        events = self._tail(self.EVENTS, self.lookback_cycles)
        cycles = len(events)

        decisions = {}
        executions = 0
        suppressed = 0
        reasons = {}
        for d in events:
            dec = d.get("decision") or d.get("final_decision") or "NONE"
            decisions[dec] = decisions.get(dec, 0) + 1
            if dec == "EXECUTE":
                executions += 1

            tc = d.get("top_candidate") or {}
            comp = tc.get("composite_score")
            dconf = tc.get("direction_confidence")
            qualified = (
                isinstance(comp, (int, float)) and comp >= self.COMPOSITE_EXECUTE_MIN
                and isinstance(dconf, (int, float)) and dconf >= self.DIRECTION_CONFIDENCE_MIN
            )
            # A candidate that met EXECUTE thresholds but did not trade is a
            # suppressed signal, whether it was demoted during scoring
            # (result != EXECUTE) or cleared scoring and was refused by the
            # decision layer (result == EXECUTE, decision != EXECUTE). Keying
            # this off the candidate's own result missed the latter entirely and
            # reported a false all-clear.
            if qualified and dec != "EXECUTE":
                suppressed += 1
                reason = self._attribute(tc, d)
                reasons[reason] = reasons.get(reason, 0) + 1

        dominant = max(reasons, key=reasons.get) if reasons else None

        if executions == 0 and suppressed > 0:
            verdict = "FLAT_WITH_SUPPRESSED_SIGNAL"
            interpretation = (
                f"ALARM: {suppressed} EXECUTE-qualified candidate(s) blocked across the "
                f"last {cycles} cycles with 0 executions. Dominant blocking gate: "
                f"{dominant}. A real signal is being thrown away."
            )
        elif executions == 0:
            verdict = "FLAT_NO_QUALIFIED_SIGNAL"
            interpretation = (
                f"Flat across the last {cycles} cycles, and no candidate met EXECUTE "
                f"thresholds (composite>={self.COMPOSITE_EXECUTE_MIN}, "
                f"direction_confidence>={self.DIRECTION_CONFIDENCE_MIN}). This is "
                f"legitimate discipline, not a suppressed signal."
            )
        else:
            verdict = "EXECUTING"
            interpretation = (
                f"{executions} execution(s) across the last {cycles} cycles."
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "FLAT_DAY_DIAGNOSTICS",
            "lookback_cycles": self.lookback_cycles,
            "cycles_analyzed": cycles,
            "latest_decision_at": events[-1].get("timestamp") if events else None,
            "decision_distribution": decisions,
            "executions": executions,
            "suppressed_executions": suppressed,
            "suppression_reasons": reasons,
            "dominant_suppression_reason": dominant,
            "execute_thresholds": {
                "composite_score_min": self.COMPOSITE_EXECUTE_MIN,
                "direction_confidence_min": self.DIRECTION_CONFIDENCE_MIN,
            },
            "verdict": verdict,
            "interpretation": interpretation,
            "status": "FLAT_DAY_DIAGNOSTICS_READY",
        }
