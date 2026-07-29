"""Unified opportunity board — every LIVE candidate the harvesting sleeves are considering, shown
together in ONE place, grouped by edge and sorted by each edge's NATIVE score.

Deliberately NOT a single cross-instrument ranking. A directional equity's expected excess return and
a defined-risk condor's credit are different units; forcing them onto one "expected profit" axis on
edges that are weak/unproven would be false precision — the fake-edge trap GreyLine has hit before.
So this renders each sleeve's own decision side by side (full visibility, honest per-edge scoring) and
leaves cross-instrument EV ranking for when EdgePersistence has measured each sleeve's REALIZED edge.

Pure aggregator: it reads what the sleeve engines already decided (engines decide, displays render).
It NEVER streams option chains (that hangs after hours) — VRP shows as a state row that scores at the
open. Every source is wrapped so one sleeve failing can't blank the whole board.
"""

import json
from datetime import datetime, date
from pathlib import Path
from os import getenv


class UnifiedOpportunityBoardEngine:

    MOM_CACHE = Path("app/data/momentum_reversal/top_candidates_cache.json")
    MOM_STATE = Path("app/data/momentum_reversal/rebalance_state.json")

    @staticmethod
    def _f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    # ---- source 1: directional equity (momentum-reversal) -----------------------------------
    def _momentum_group(self):
        try:
            d = json.loads(self.MOM_CACHE.read_text())
            cands = d.get("candidates") or []
            # apply the same trash failsafe the panels use, so the board can never surface junk
            from app.services.trash_pick_filter_engine import TrashPickFilterEngine
            cands, _ = TrashPickFilterEngine.partition(cands)
        except Exception as e:
            return {"strategy": "Momentum-Reversal", "instrument": "EQUITY", "error": str(e)[:120],
                    "candidates": []}

        # LIVE executability per name — the SAME classification the Execute/Watch panel uses, so all
        # three surfaces agree on whether a pick can actually fire and why not.
        exec_stat = {}
        try:
            from app.services.execute_watch_engine import ExecuteWatchEngine
            exec_stat = {str(w.get("symbol") or "").upper(): w
                         for w in (ExecuteWatchEngine().view().get("watch") or [])}
        except Exception:
            exec_stat = {}

        rows = []
        for c in cands:
            sym = str(c.get("symbol") or "").upper()
            w = exec_stat.get(sym) or {}
            rows.append({
                "symbol": sym,
                "instrument": "EQUITY",
                "side": c.get("side"),
                "score": round(self._f(c.get("conviction")), 3),
                "score_label": "conviction",
                "status": w.get("status") or "—",
                "reason": w.get("reason") or "",
                "detail": (f"12-1 mom {round(self._f(c.get('momentum_12_1_pct')),0):.0f}% · "
                           f"5d rev {round(self._f(c.get('reversal_5d_move_pct')),0):.0f}% · "
                           f"${self._f(c.get('last_close')):.2f}"),
            })
        rows.sort(key=lambda r: r["score"], reverse=True)   # native sort: by conviction

        # cadence: these are real picks but only OPEN on the 7-day rebalance, so say when.
        next_due = None
        try:
            st = json.loads(self.MOM_STATE.read_text())
            from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine as R
            last = datetime.fromisoformat(str(st.get("last_rebalance_at"))).date()
            nd = date.fromordinal(last.toordinal() + R.MIN_CALENDAR_DAYS)
            next_due = nd.isoformat()
        except Exception:
            pass
        return {
            "strategy": "Momentum-Reversal (directional)",
            "edge": "12-1 momentum + 5-day reversal, traded as whole-share EQUITY (long-only, regime-gated)",
            "instrument": "EQUITY",
            "score_basis": "conviction (percentile-rank blend of the two legs, 0-2)",
            "action": (f"rebalances on a 7-day cadence — next due {next_due}" if next_due
                       else "rebalances on a 7-day cadence"),
            "candidates": rows,
        }

    # ---- source 2: earnings IV-crush (defined-risk condor) ----------------------------------
    def _earnings_group(self):
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            st = EarningsVolHarvestEngine().status()
        except Exception as e:
            return {"strategy": "Earnings IV-Crush", "instrument": "OPTION", "error": str(e)[:120],
                    "candidates": []}
        rows = []
        for c in (st.get("candidates_now") or []):
            rows.append({
                "symbol": str(c.get("ticker") or "").upper(),
                "instrument": "OPTION (short condor)",
                "side": "SELL_PREMIUM",
                "score": round(self._f(c.get("iv_rank")) * 100, 1),   # 0-100 for a readable score
                "score_label": "IV rank",
                "status": "ARMED",
                "reason": f"sells a condor in-session before the {c.get('report_date')} report",
                "detail": (f"reports {c.get('report_date')} (T-{c.get('days_to_report')}) · "
                           f"implied move {self._f(c.get('implied_move_pct')):.1f}%"),
            })
        rows.sort(key=lambda r: r["score"], reverse=True)   # native sort: by IV rank
        return {
            "strategy": "Earnings IV-Crush",
            "edge": "sell a defined-risk condor into a rich-IV name's earnings, harvest the IV crush",
            "instrument": "OPTION (short condor)",
            "score_basis": "IV rank 0-100 (how rich implied vol is vs its own year)",
            "action": (f"armed · {st.get('open_positions', 0)} open · "
                       f"${self._f(st.get('open_risk_usd')):.0f}/${self._f(st.get('portfolio_cap_usd')):.0f} risk used · "
                       "opens once/day in-session before the report"),
            "candidates": rows,
        }

    # ---- source 3: variance risk premium (defined-risk condor) — STATE ROW, no chain stream --
    def _vrp_group(self):
        try:
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
            eng = ConditionalVRPShortPremiumEngine()
            armed = bool(eng.enabled())
            open_risk = self._f(eng._open_risk())
            cap = self._f(getattr(eng, "PORTFOLIO_RISK_CAP_USD", 1200.0))
        except Exception as e:
            return {"strategy": "Variance Risk Premium", "instrument": "OPTION", "error": str(e)[:120],
                    "candidates": []}
        return {
            "strategy": "Variance Risk Premium (VRP)",
            "edge": "sell index/liquid-equity condors to harvest the variance risk premium (rich IV)",
            "instrument": "OPTION (short condor)",
            "score_basis": "condor EV = market-implied POP x credit vs defined risk (scored per contract)",
            "action": (f"{'armed' if armed else 'OFF'} · ${open_risk:.0f}/${cap:.0f} risk used · "
                       "scores contracts DURING the session (needs the live option-chain stream)"),
            # No discrete after-hours pick list: VRP isn't a ranked name list, it's a condition-driven
            # harvester whose contracts can only be priced from live chains. Shown as a state row.
            "candidates": [],
            "note": "no discrete candidates after hours — the condor scorer runs at the open on live chains",
        }

    def board(self):
        groups = [self._momentum_group(), self._earnings_group(), self._vrp_group()]
        total = sum(len(g.get("candidates") or []) for g in groups)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "groups": groups,
            "total_candidates": total,
            "sort_policy": ("sorted WITHIN each edge by that edge's native score; NOT cross-ranked — "
                            "a directional-equity excess return and a defined-risk condor credit are "
                            "different units. A single cross-instrument ranking waits on EdgePersistence "
                            "measuring each sleeve's realized live edge (see /edge-persistence)."),
            "status": "OPPORTUNITY_BOARD",
        }
