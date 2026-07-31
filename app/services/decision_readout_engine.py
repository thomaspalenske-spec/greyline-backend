"""The single sanctioned readout of what GreyLine has ACTUALLY decided — provenance-stamped.

WHY THIS EXISTS (2026-07-30): the fantasy-vs-reality failures in operator Q&A did NOT come from
GreyLine's own surfaces — the dashboard was real and consistent throughout. They came from ANSWERS
computed off to the side: a standalone script that re-derived "the best condor" with a simplified model
(no portfolio budget) and presented it as the system's answer; a budget figure mislabeled as a max
loss; live-quote dollar values quoted to the dollar as if they were constants.

The fix is a single sanctioned READ path. This engine AGGREGATES the exact cached decisions the operator
dashboard renders — it does NOT recompute anything (that would reintroduce the divergence it exists to
prevent). Every section carries:
  * source        — which engine/cache the number came from
  * as_of         — when that decision was computed
  * point_in_time — True when the figures are derived from LIVE option quotes (they are rebuilt each
                    run and DRIFT run-to-run, even after the close), so they must never be presented as
                    fixed constants.

DISCIPLINE (the actual guard): when answering "what will the system do / what's the best X", read from
here (or the owning engine's cache) and quote it verbatim WITH its stamps — never a hand-rolled
calculation, never a bare dollar figure. Reading the same cache the dashboard reads guarantees the
answer == what the operator sees. See the [[greyline-answer-from-the-engine]] discipline memory,
[[greyline-engines-decide-displays-render]], [[greyline-reality-guard]], [[greyline-fantasy-audit]].
"""

from datetime import datetime


class DecisionReadoutEngine:

    LIVE_QUOTE_NOTE = ("figures are rebuilt from live option quotes each run and DRIFT run-to-run "
                       "(even after the close) — treat every dollar value as point-in-time (±), "
                       "never a fixed constant")

    @staticmethod
    def _section(title, source, point_in_time, loader, as_of_key=None):
        """Run one canonical reader, stamping provenance. Failures are recorded, never hidden."""
        out = {"title": title, "source": source, "point_in_time": point_in_time}
        try:
            data = loader()
        except Exception as e:
            out.update({"status": "READOUT_SECTION_DEGRADED", "error": repr(e)[:160], "data": None})
            return out
        if as_of_key and isinstance(data, dict):
            out["as_of"] = data.get(as_of_key)
        if point_in_time:
            out["precision"] = DecisionReadoutEngine.LIVE_QUOTE_NOTE
        out["data"] = data
        return out

    def readout(self, condor_limit=12):
        sections = []

        # Best iron condors — the ROR-ranked buildable condors (VRP + earnings), off live UW quotes.
        def _best():
            from app.services.best_condors_engine import BestCondorsEngine
            return BestCondorsEngine().cached(limit=condor_limit)
        sections.append(self._section(
            "Best Iron Condors (ranked, buildable)",
            "BestCondorsEngine.cached() → app/data/condor_shadow/best_condors.json",
            True, _best, as_of_key="timestamp"))

        # Opportunity Board — every live candidate across all edges, grouped, NOT cross-ranked.
        def _board():
            from app.services.unified_opportunity_board_engine import UnifiedOpportunityBoardEngine
            return UnifiedOpportunityBoardEngine().board()
        sections.append(self._section(
            "Opportunity Board (all edges, grouped)",
            "UnifiedOpportunityBoardEngine.board()",
            True, _board, as_of_key="timestamp"))

        # Execute / Watch — the momentum equity picks + live executability (QUEUED/BLOCKED/WATCH).
        def _ew():
            from app.services.execute_watch_engine import ExecuteWatchEngine
            return ExecuteWatchEngine().view()
        sections.append(self._section(
            "Execute / Watch (momentum equity executability)",
            "ExecuteWatchEngine.view()",
            False, _ew, as_of_key="candidates_as_of"))

        # Optionable universe — the derived VRP/condor candidate universe (daily close screen).
        def _uni():
            from app.services.optionable_universe_engine import OptionableUniverseEngine
            return OptionableUniverseEngine().report(limit=400)
        sections.append(self._section(
            "Optionable Universe (derived, daily close)",
            "OptionableUniverseEngine.report()",
            False, _uni, as_of_key="session_date"))

        degraded = [s["title"] for s in sections if s.get("status") == "READOUT_SECTION_DEGRADED"]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "what_this_is": ("The single sanctioned readout: the SAME cached decisions the operator "
                             "dashboard renders, aggregated and provenance-stamped. Nothing here is "
                             "recomputed — reading it guarantees this matches what the dashboard shows."),
            "how_to_read": ("Sections flagged point_in_time=True are derived from live option quotes and "
                            "vary run-to-run; their dollar figures are approximate (±), not constants."),
            "sections": sections,
            "degraded_sections": degraded,
            "status": "DECISION_READOUT_DEGRADED" if degraded else "DECISION_READOUT_OK",
        }
