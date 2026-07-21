"""Trade the strategy's directional picks as OPTIONS, not shares — the options-trader core.

Operator directive: GreyLine trades options, not stocks. This bridges the directional
signal to options execution: each pick becomes a call (bullish) or put (bearish), gated by
whether a $10k account can actually hold the contract, with the validated Dynamic-TPS 4-TP
exit doctrine attached.

Two realities are built IN rather than argued about, so this is a DISCIPLINED options
trader, not a naive one:

  * AFFORDABILITY GATE. Most high-priced names are untradeable as options at $10k — a
    near-money SNDK call is ~$17,000/contract against a $1,000 slice. Those are SKIPPED and
    reported, never force-sized. Only names whose cheapest usable contract fits the per-name
    budget are traded. As the account grows, more names clear the gate automatically.

  * THETA-AWARE EXPIRY. The directional edge plays out over days, so a weekly option bleeds
    to decay before the move arrives. This prefers ~30-45 DTE, far enough out that theta is
    slow over the intended hold, and never the front-week contract.

The honest caveat, once: on a thin momentum edge (~0.23%/5d) options still lose to premium
and theta — this engine does not manufacture edge, it executes whatever signal drives it as
options. Its value is being READY for a signal with the conviction to justify options
(the flow doctrine, if it proves out), while doing exactly what the operator directed now.
"""

from datetime import datetime, timedelta, timezone

from app.services.options_cycle_engine import OptionsCycleEngine
from app.services.options_dynamic_tps_engine import OptionsDynamicTPSEngine
from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine


class MomentumOptionsExecutionEngine:

    TARGET_DTE = 35            # ~5 weeks: past the front-week theta cliff, still liquid
    MIN_DTE = 21
    MAX_DTE = 60

    def __init__(self, capital_base=10000.0, max_position_pct=0.10, top_n=10):
        self.capital_base = float(capital_base)
        self.max_position_pct = float(max_position_pct)
        self.top_n = int(top_n)
        self.cycle = OptionsCycleEngine()
        self.chain = TradeStationOptionChainLiveEngine()
        self.tps = OptionsDynamicTPSEngine()
        self.doctrine = TradeDoctrineEngine()

    # ---- expiry selection (theta-aware) ------------------------------------
    def _target_expiration(self, symbol, today=None):
        """Nearest listed expiry to TARGET_DTE within [MIN_DTE, MAX_DTE], or None.

        Unlike the entry-quality floor (>= 7 DTE), a directional hold wants distance from the
        theta cliff, so this centres on ~35 DTE rather than grabbing the nearest weekly.
        """
        today = today or datetime.now(timezone.utc).date()
        listing = self.chain.get_expirations(symbol) or {}
        best, best_gap = None, None
        for raw in listing.get("expirations") or []:
            try:
                d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            dte = (d - today).days
            if self.MIN_DTE <= dte <= self.MAX_DTE:
                gap = abs(dte - self.TARGET_DTE)
                if best is None or gap < best_gap:
                    best, best_gap = d.isoformat(), gap
        return best

    # ---- per-name affordability probe --------------------------------------
    def _affordable_contract(self, symbol, option_type, budget, expiration):
        """Cheapest usable contract whose cost fits `budget`, or None with a reason.

        Returns (contract, cost, n_contracts) — n_contracts is how many the budget buys.
        """
        snap = self.chain.get_chain_snapshot(symbol=symbol, expiration=expiration,
                                             option_type="Call" if option_type == "CALL" else "Put",
                                             max_contracts=50)
        side = "Call" if option_type == "CALL" else "Put"
        best = None
        for c in snap.get("contracts", []) or []:
            if c.get("Side") and c.get("Side") != side:
                continue
            try:
                px = float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            cost = px * 100
            if cost <= budget and (best is None or cost < best[1]):
                best = (c, cost)
        if not best:
            return None
        contract, cost = best
        return contract, cost, int(budget // cost)

    # ---- plan (dry-run capable) --------------------------------------------
    def plan(self, targets):
        """Turn directional picks into an options plan — no orders placed.

        `targets`: list of {symbol, side, directional_bias, last_close, conviction, ...}
        from MomentumReversalStrategyEngine.select. Returns the tradeable options plus the
        skipped names with reasons, so the affordability truth is visible, never hidden.
        """
        budget = self.capital_base * self.max_position_pct
        tradeable, skipped = [], []
        for t in targets[:self.top_n]:
            symbol = t.get("symbol")
            option_type = "PUT" if str(t.get("side", "")).upper() in ("SELL", "SELL_SHORT", "SHORT") else "CALL"
            exp = self._target_expiration(symbol)
            if not exp:
                skipped.append({"symbol": symbol, "reason": "NO_EXPIRY_IN_DTE_WINDOW"})
                continue
            got = self._affordable_contract(symbol, option_type, budget, exp)
            if not got:
                skipped.append({"symbol": symbol, "option_type": option_type,
                                "reason": "NO_AFFORDABLE_CONTRACT", "budget": round(budget, 2)})
                continue
            contract, cost, n = got
            # ATR-free: without an ATR feed here the exit ladder is expressed in % of the
            # option's own premium via the Dynamic-TPS engine's contract allocation, which
            # is what actually gets managed. Entry premium is the reference the stop ratchets
            # from. (ATR-based underlying targets are a later refinement.)
            alloc = self.tps.allocate(n)
            tradeable.append({
                "symbol": symbol, "option_type": option_type, "expiration": exp,
                "strike": contract.get("Strike"), "premium_per_contract": round(cost / 100, 2),
                "contracts": n, "cost": round(cost * n, 2),
                "directional_bias": t.get("directional_bias"),
                "conviction": t.get("conviction"),
                "exit": {"mode": alloc["mode"], "contracts_at_target": alloc["targets"],
                         "runner": alloc["runner"],
                         "doctrine": "Dynamic-TPS: bank at targets where size allows, "
                                     "ratchet the stop on every target reached, run the tail"},
            })
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MomentumOptionsExecutionEngine",
            "per_name_budget": round(budget, 2),
            "tradeable": tradeable,
            "skipped": skipped,
            "tradeable_count": len(tradeable),
            "skipped_count": len(skipped),
            "note": (f"{len(tradeable)} of {min(len(targets), self.top_n)} picks are tradeable "
                     f"as options at ${self.capital_base:,.0f}; the rest priced out. This grows "
                     "as the account grows."),
            "status": "MOMENTUM_OPTIONS_PLAN_READY",
        }
