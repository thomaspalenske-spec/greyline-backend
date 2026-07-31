"""The unified face of the OS. One coherent view of the whole Variance Premium Harvesting Machine.

Sixteen hypotheses established what GreyLine actually is: not an alpha oracle (no predictive edge
exists in this data) but a Variance Risk Premium Harvesting Operating System. Its parts were built
one at a time; this ties them into a single picture so the OS can be seen and reasoned about as one
thing:

  1. PREMIUM CATALOG   — every real, measurable premium being harvested, from the honest registry
  2. HARVEST UNIVERSE  — where each premium lives (equity indices + cross-asset), measured not guessed
  3. STRUCTURE         — how it's expressed (defined-risk condors, put-tilt, skew-timed selection)
  4. RISK BUDGET       — the portfolio tail cap and how much is deployed
  5. CATALYST DEFENSE  — whether a scheduled vol event is deferring new premium
  6. OUT-OF-SAMPLE     — the only honest scoreboard: what the forward panels have resolved

It computes nothing new — it reads the engines of record. A read-only lens, so it can never
disagree with the systems it summarises.
"""

from datetime import datetime


class PremiumHarvestOSEngine:

    def status(self):
        out = {"timestamp": datetime.utcnow().isoformat(),
               "identity": "Variance Risk Premium Harvesting OS",
               "thesis": "harvest every real premium, predict nothing, bound the tail structurally"}

        # 1. PREMIUM CATALOG — surviving candidates from the honest registry
        try:
            from app.services.edge_discovery_registry_engine import EdgeDiscoveryRegistryEngine
            reg = EdgeDiscoveryRegistryEngine().status()
            out["premium_catalog"] = {
                "hypotheses_tested": reg.get("hypotheses_tested"),
                "surviving_candidates": reg.get("surviving_candidates"),
                "verdict_counts": reg.get("verdict_counts"),
            }
        except Exception as e:
            out["premium_catalog"] = {"error": str(e)[:80]}

        # 2/3. HARVEST UNIVERSE + STRUCTURE
        try:
            from app.services.conditional_vrp_short_premium_engine import (
                ConditionalVRPShortPremiumEngine, INDEX_ETFS, CROSS_ASSET_ETFS)
            sp = ConditionalVRPShortPremiumEngine()
            out["harvest"] = {
                "armed": sp.enabled(),
                "equity_index_premium": INDEX_ETFS,
                "cross_asset_premium": CROSS_ASSET_ETFS,
                "structure": {
                    "vehicle": "defined-risk iron condors (wings cap every tail)",
                    "put_tilt": f"put {sp._put_delta()}d / call {sp._call_delta()}d "
                                f"(harvest the overpriced put skew)",
                    "selection": "richest-skew names first (skew-timing: ~54% more premium)",
                    "per_position_cap_usd": sp.MAX_LOSS_PER_POSITION_USD,
                    "portfolio_tail_cap_usd": sp.PORTFOLIO_RISK_CAP_USD,
                },
            }
        except Exception as e:
            out["harvest"] = {"error": str(e)[:80]}

        # 4. RISK BUDGET — deployed vs the portfolio tail cap
        try:
            sp = sp  # noqa
            deployed = sp._open_risk()
            out["risk_budget"] = {
                "portfolio_tail_cap_usd": sp.PORTFOLIO_RISK_CAP_USD,
                "deployed_defined_risk_usd": round(deployed, 2),
                "headroom_usd": round(sp.PORTFOLIO_RISK_CAP_USD - deployed, 2),
                "open_positions": len(sp._open_symbols()),
                "vega_budget_usd": sp._vega_budget(),
                "note": "TWO risk dimensions like a vol desk: max loss (dollar cap, the tail) AND "
                        "net short-vega (the vol exposure). Worst case is the whole dollar cap lost "
                        "in a correlated crash — bounded by design.",
            }
        except Exception as e:
            out["risk_budget"] = {"error": str(e)[:80]}

        # 5. CATALYST DEFENSE
        try:
            from app.services.catalyst_risk_overlay_engine import CatalystRiskOverlayEngine
            out["catalyst_defense"] = CatalystRiskOverlayEngine().status()
        except Exception as e:
            out["catalyst_defense"] = {"error": str(e)[:80]}

        # 6. OUT-OF-SAMPLE SCOREBOARD — the only honest verdict, accruing live
        try:
            from app.services.index_variance_premium_panel_engine import IndexVariancePremiumPanelEngine
            ivp = IndexVariancePremiumPanelEngine().status()
            out["out_of_sample_scoreboard"] = {
                "pending": ivp.get("pending_entries"),
                "resolved": ivp.get("resolved_out_of_sample"),
                "needed_for_verdict": ivp.get("needed_for_verdict"),
                "verdict": ivp.get("verdict"),
                "caveat": ("the backtest is one crash-free year; only this out-of-sample panel can "
                           "eventually price the crash the backtest can't show"),
            }
        except Exception as e:
            out["out_of_sample_scoreboard"] = {"error": str(e)[:80]}

        # 7. BOOK GREEKS — the vol-desk view: is the harvest a PURE vol bet or a directional one?
        try:
            from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
            g = PortfolioGreeksEngine().book_greeks()
            out["book_greeks"] = {k: g.get(k) for k in
                ("net_delta_shares", "net_vega", "net_theta", "delta_neutral", "delta_hedge", "open_legs")}
        except Exception as e:
            out["book_greeks"] = {"error": str(e)[:80]}

        # 8. CRASH STRESS — the return-vs-ruin truth: the live book's loss under real vol crashes,
        # bounded by the defined-risk cap. Proves the tail is survivable, not wished away.
        try:
            from app.services.crash_stress_test_engine import CrashStressTestEngine
            out["crash_stress"] = CrashStressTestEngine().stress_current_book()
        except Exception as e:
            out["crash_stress"] = {"error": str(e)[:80]}

        # Top-level degraded rollup so a programmatic consumer / the reality guard can tell this
        # unified view is degraded without walking all 8 sections (mirrors unified_board.degraded_edges
        # and decision_readout.degraded_sections). Each section already captures its own {"error": ...}.
        _sections = ("premium_catalog", "harvest", "risk_budget", "catalyst_defense",
                     "out_of_sample_scoreboard", "book_greeks", "crash_stress")
        degraded = [k for k in _sections if isinstance(out.get(k), dict) and out[k].get("error")]
        out["degraded_sections"] = degraded
        out["status"] = "PREMIUM_HARVEST_OS_DEGRADED" if degraded else "PREMIUM_HARVEST_OS_STATUS"
        return out
