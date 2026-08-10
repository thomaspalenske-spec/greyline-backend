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

        # Names the EQUITY shadow currently "holds" (its open weekly cohort) show on the Momentum Shadow
        # Open Positions card — hide them here too, so the board stays a genuine "NOT executed / next up"
        # bench rather than repeating the shadow's holdings. Fails open (no shadow -> hide nothing).
        shadow_open = set()
        try:
            from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine
            shadow_open = MomentumReversalShadowEngine().open_symbols()
        except Exception:
            shadow_open = set()

        rows = []
        held = 0
        shadow_hidden = 0
        for c in cands:
            sym = str(c.get("symbol") or "").upper()
            w = exec_stat.get(sym) or {}
            status = w.get("status") or "—"
            # Names already HELD live in the Open Positions table — hide them here so the board is a
            # clean "what's next up" view (full visibility into the queued candidates, not a repeat of
            # what we already own).
            if str(status).upper() == "BOUGHT":
                held += 1
                continue
            if sym in shadow_open:            # already "open" in the shadow -> on the shadow positions card
                shadow_hidden += 1
                continue
            rows.append({
                "symbol": sym,
                "instrument": "EQUITY",
                "price": self._f(c.get("last_close")),   # latest daily close (same value shown in detail)
                "side": c.get("side"),
                "score": round(self._f(c.get("conviction")), 3),
                "score_label": "conviction",
                "status": status,
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
            "held_hidden": held,
            "held_note": (f"{held} held name(s) hidden — they're in Open Positions. Still fully analyzed "
                          f"each rebalance (GreyLine can add to a position it already owns)." if held else ""),
            "shadow_open_hidden": shadow_hidden,
            "shadow_open_note": (f"{shadow_hidden} name(s) hidden — the equity shadow is currently 'holding' "
                                 f"them (Momentum Shadow Open Positions). This board shows what's NOT yet "
                                 f"executed." if shadow_hidden else ""),
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
                # reflect the ACTUAL arm state — the sleeve can be disabled (don't paint a disabled
                # sleeve's candidates green "ARMED" as if they'll fire).
                "status": ("ARMED" if st.get("armed") else "OFF"),
                "reason": (f"sells a condor in-session before the {c.get('report_date')} report"
                           if st.get("armed") else
                           f"earnings sleeve OFF — would sell a condor before the {c.get('report_date')} report if armed"),
                "detail": (f"reports {c.get('report_date')} (T-{c.get('days_to_report')}) · "
                           f"implied move {self._f(c.get('implied_move_pct')):.1f}%"),
            })
        rows.sort(key=lambda r: r["score"], reverse=True)   # native sort: by IV rank
        return {
            "strategy": "Earnings IV-Crush",
            "edge": "sell a defined-risk condor into a rich-IV name's earnings, harvest the IV crush",
            "instrument": "OPTION (short condor)",
            "score_basis": "IV rank 0-100 (how rich implied vol is vs its own year)",
            "action": (f"{'armed' if st.get('armed') else 'OFF'} · {st.get('open_positions', 0)} open · "
                       f"${self._f(st.get('open_risk_usd')):.0f}/${self._f(st.get('portfolio_cap_usd')):.0f} risk used · "
                       "opens once/day in-session before the report"),
            "candidates": rows,
        }

    # ---- source 3: variance risk premium (defined-risk condor) — off Unusual Whales --------------
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
        # Buildable VRP condors come from the SAME Unusual-Whales-sourced cache the Best Iron Condors
        # card reads. UW works after hours (the SIM chain stream is dark then), so this section is
        # populated round-the-clock. Full economics (gain/loss/strikes) stay on Best Iron Condors — here
        # we show the candidate NAMES scored by IV rank, consistent with the Earnings IV-Crush group.
        rows = []
        vrp_error = None
        try:
            from app.services.best_condors_engine import BestCondorsEngine
            cached = BestCondorsEngine().cached(limit=50)
            # If the VRP sleeve THREW when best_condors last recomputed, its condors are absent — a broken
            # sleeve, NOT a calm "none right now". Read best_condors' sleeve_errors so a failure surfaces
            # as an error (→ degraded_edges, card renders red) instead of the benign empty note below.
            vrp_error = (cached.get("sleeve_errors") or {}).get("VRP")
            for c in (cached.get("condors") or []):
                if str(c.get("sleeve") or "").upper() != "VRP":
                    continue
                gain, loss = self._f(c.get("max_gain_usd")), self._f(c.get("max_loss_usd"))
                ror = self._f(c.get("return_on_risk")) * 100
                rows.append({
                    "symbol": str(c.get("symbol") or "").upper(),
                    "instrument": "OPTION (short condor)",
                    "side": "SELL_PREMIUM",
                    "score": round(self._f(c.get("iv_rank")) * 100, 1),   # 0-100, same unit as earnings
                    "score_label": "IV rank",
                    "status": ("ARMED" if armed else "OFF"),
                    "reason": (f"sells a defined-risk condor to harvest rich IV — ${gain:.0f} credit / "
                               f"${loss:.0f} risk" if armed else
                               "VRP sleeve OFF — would sell a rich-IV condor if armed"),
                    "detail": (f"exp {c.get('expiration')} · SP {c.get('short_put')} · "
                               f"SC {c.get('short_call')} · R/R {ror:.0f}% (full economics on Best Iron Condors)"),
                })
        except Exception as e:
            vrp_error = repr(e)[:160]
        rows.sort(key=lambda r: r["score"], reverse=True)   # native sort: by IV rank
        out = {
            "strategy": "Variance Risk Premium (VRP)",
            "edge": "sell index/liquid-equity condors to harvest the variance risk premium (rich IV)",
            "instrument": "OPTION (short condor)",
            "score_basis": ("IV rank 0-100 (how rich implied vol is vs its own year); "
                            "ranked economics on the Best Iron Condors card"),
            "action": (f"{'armed' if armed else 'OFF'} · ${open_risk:.0f}/${cap:.0f} risk used · "
                       f"{len(rows)} buildable condor(s) off Unusual Whales"),
            "candidates": rows,
        }
        if vrp_error:
            # a broken sleeve is degraded, not empty — board().degraded_edges reads g["error"]
            out["error"] = f"VRP condor build failed: {vrp_error}"
        elif not rows:
            out["note"] = "no buildable VRP condors cached right now — refreshes each scheduler cycle"
        return out

    @staticmethod
    def _on(flag):
        from os import getenv
        return (getenv(flag, "") or "").strip().lower() == "true"

    def board(self):
        # The condor sleeves (earnings-vol IV-crush, VRP) were RETIRED 2026-08-04 — the SIM can't price
        # atomic condor closes — so a DISABLED condor sleeve must not paint the board with "OFF, would sell
        # if armed" candidates for a strategy we've decided not to trade (it reads as still-live). Include a
        # condor sleeve ONLY when it's actually enabled; re-arming its flag re-surfaces its candidates.
        # Momentum stays regardless — it's a kill-switch (disarmed-but-viable), not a retired strategy.
        groups = [self._momentum_group()]
        if self._on("GREYLINE_EARNINGS_VOL_ENABLED"):
            groups.append(self._earnings_group())
        if self._on("GREYLINE_VRP_SHORT_PREMIUM_ENABLED"):
            groups.append(self._vrp_group())
        total = sum(len(g.get("candidates") or []) for g in groups)
        # A top-level flag for PROGRAMMATIC consumers (the reality guard): a group that threw is already
        # surfaced per-group (its `error` key, rendered red on the card), but nothing could see "a sleeve
        # is broken" without walking the groups. Now it can.
        degraded_edges = [g.get("strategy") for g in groups if g.get("error")]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "groups": groups,
            "total_candidates": total,
            "degraded_edges": degraded_edges,
            "sort_policy": ("sorted WITHIN each edge by that edge's native score; NOT cross-ranked — "
                            "a directional-equity excess return and a defined-risk condor credit are "
                            "different units. A single cross-instrument ranking waits on EdgePersistence "
                            "measuring each sleeve's realized live edge (see /edge-persistence)."),
            "status": "OPPORTUNITY_BOARD_DEGRADED" if degraded_edges else "OPPORTUNITY_BOARD",
        }
