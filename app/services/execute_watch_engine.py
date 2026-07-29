"""Execute / Watch — surface buy opportunities and WHY they haven't fired.

The momentum candidate engine produces the ranked buy opportunities. This annotates them so the
operator can see, at a glance:
  * WATCH — the opportunities ranked top-to-bottom by conviction (closest to firing on top).
  * EXECUTE — a candidate that MEETS the buy criteria but can't fire: blocked by no free capital,
    a rejected/glitched order, or (meets criteria + has capital yet still not deployed) a strategy
    that should be firing and isn't. This is the "wanted to buy, got blocked" visibility — the same
    class of silent failure that hid the rejected sells.

Read-only. Reads the CACHED candidate list (a full universe scan is ~minutes — far too heavy here),
so it says how stale that cache is instead of recomputing.
"""

import json
from datetime import datetime
from pathlib import Path
from os import getenv


class ExecuteWatchEngine:

    CACHE = Path("app/data/momentum_reversal/top_candidates_cache.json")
    SLEEVE_INSTRUMENTS = {"SVXY", "QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC", "SGOV"}
    MOMENTUM_TOP_N = 10

    @staticmethod
    def _f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    def _candidates(self):
        try:
            d = json.loads(self.CACHE.read_text())
            return d.get("candidates") or [], d.get("as_of"), d.get("data_source")
        except Exception:
            return [], None, None

    def _compute_time_discards(self):
        """Trash discarded at COMPUTE time (before it ever reached the cached candidate list) — so
        the panel can still show what was thrown out even when nothing trash survived into the cache."""
        try:
            d = json.loads(self.CACHE.read_text())
            return d.get("trash_discarded_names") or []
        except Exception:
            return []

    def _held_symbols(self):
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            rj = TradeStationPositionsLiveEngine().get_positions().get("response_json") or {}
            return {str(p.get("Symbol")).split()[0].upper() for p in (rj.get("Positions") or [])
                    if int(self._f(p.get("Quantity"))) != 0}
        except Exception:
            return set()

    def _rejected_symbols(self):
        """Symbols with a recent REJECTED order — a glitch that blocked execution."""
        try:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            out = set()
            for o in ((TradeStationSimBookingEngine().orders().get("response_json") or {}).get("Orders") or []):
                if str(o.get("StatusDescription")) == "Rejected":
                    out.add(str((o.get("Legs") or [{}])[0].get("Symbol") or "").split()[0].upper())
            return out
        except Exception:
            return set()

    def _free_cash(self):
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            eq, dep = MissionRiskGovernorEngine()._equity_and_deployed()
            return round(eq - dep, 2)
        except Exception:
            return 0.0

    def view(self):
        cands, as_of, source = self._candidates()
        # FAILSAFE: discard trash picks (penny stocks / artifact momentum / crashes) — only clean,
        # confirmed picks are shown or acted on. Same filter the execution path uses.
        from app.services.trash_pick_filter_engine import TrashPickFilterEngine
        cands, discarded = TrashPickFilterEngine.partition(cands)
        # merge in trash the compute step already dropped (never made it into the cache), so the
        # operator sees the full "thrown out" picture, not just what survived to serve-time.
        seen = {str(d.get("symbol") or "").upper() for d in discarded}
        for t in self._compute_time_discards():
            if str(t.get("symbol") or "").upper() not in seen:
                discarded.append({"symbol": t.get("symbol"), "last_close": t.get("last_close"),
                                  "discard_reason": t.get("reason")})
        held = self._held_symbols()
        rejects = self._rejected_symbols()
        free_cash = self._free_cash()
        try:
            mom_cap = float(getenv("GREYLINE_MOMENTUM_CAPITAL_USD", "") or 0)
        except (TypeError, ValueError):
            mom_cap = 0.0
        per_name = mom_cap / self.MOMENTUM_TOP_N if self.MOMENTUM_TOP_N else 0.0
        # momentum's own free slots = its cap not yet spent on momentum names
        mom_held = len(held - self.SLEEVE_INSTRUMENTS)
        free_slots = max(0, self.MOMENTUM_TOP_N - mom_held)

        watch = []
        for i, c in enumerate(cands):                         # cache is already ranked by conviction
            sym = str(c.get("symbol") or "").upper()
            cost = self._f(c.get("last_close")) or per_name
            if sym in held:
                status, reason = "BOUGHT", "held"
            elif sym in rejects:
                status, reason = "EXECUTE", "blocked: order rejected (glitch)"
            elif mom_cap <= 0:
                status, reason = "WATCH", "momentum unfunded ($0 capital)"
            elif free_cash < cost:
                status, reason = "EXECUTE", f"blocked: no free capital (need ~${round(cost)}, have ${round(free_cash)})"
            elif i < free_slots:
                status, reason = "EXECUTE", ("meets signal + capital, not deployed — momentum may be "
                                             "filtering it (price/liquidity) or the rebalance is stalled")
            else:
                status, reason = "WATCH", f"ranked below the buy cutoff (slot {i+1} > {free_slots} free)"
            watch.append({"rank": c.get("rank", i + 1), "symbol": sym,
                          "direction": c.get("direction"), "conviction": c.get("conviction"),
                          "last_close": c.get("last_close"),
                          "momentum_12_1_pct": c.get("momentum_12_1_pct"),
                          "reversal_5d_move_pct": c.get("reversal_5d_move_pct"),
                          "status": status, "reason": reason})

        execute_blocked = [w for w in watch if w["status"] == "EXECUTE"]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "candidates_as_of": as_of, "data_source": source,
            "free_cash": free_cash, "momentum_capital": mom_cap, "momentum_free_slots": free_slots,
            "execute_blocked_count": len(execute_blocked),
            "execute_blocked": execute_blocked,
            "watch": watch,                                   # ranked, closest-to-firing on top (clean only)
            "discarded_trash_count": len(discarded),
            "discarded_trash": [{"symbol": d.get("symbol"), "last_close": d.get("last_close"),
                                 "reason": d.get("discard_reason")} for d in discarded],
            "note": ("WATCH = buy opportunities ranked by conviction (closest to firing on top). "
                     "EXECUTE = meets criteria but can't fire (no capital / glitch / should-fire-but-"
                     "not-deployed). Candidates from the cached universe scan — see candidates_as_of."),
            "status": "EXECUTE_WATCH",
        }
