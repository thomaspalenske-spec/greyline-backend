"""Run the validated exit doctrine on an options position too small to quarter.

The doctrine (TradeDoctrineEngine, validated by MDMP war-game) banks 25% at 1.5, 3.0 and
4.5 ATR and lets the last 25% run on a 3-ATR trailing stop. That needs at least 4 units.
A $10k account caps a position at $500 and a contract is 100 shares of premium, so most
names afford 1-3 contracts: measured 2026-07-20, SPY had 20 of 50 contracts affordable
while INTC and MU had ZERO. Without this, the doctrine simply cannot be applied to the
instrument the operator actually wants to trade.

THE INSIGHT THAT MAKES SMALL SIZE WORK: the doctrine has TWO mechanisms, and only one of
them needs quantity.

  * BANKING (sell 25%) reduces exposure. It requires >= 4 units.
  * RATCHETING (stop -> breakeven -> TP1 -> trailing) protects profit. It is
    quantity-independent and works identically on a single contract.

So a target being REACHED always advances the stop, whether or not a contract could be
sold for it. The risk profile of the doctrine is preserved at any size; only the
profit-banking degrades. A 1-contract position is therefore the doctrine's runner phase
from the outset, wrapped in the same ratcheting stop the 4-contract version uses.

That also satisfies the mission's first-target rule — "the first TP should recoup the
initial cost of the contract" — in the only way available at size 1. You cannot sell half
a contract to get your premium back, but ratcheting the stop to breakeven at TP1 means you
can no longer LOSE the premium. Same intent, expressed through the stop instead of through
quantity.

ALLOCATION. Contracts are distributed across the doctrine's four exits (three targets plus
the runner) by largest remainder on its own 25/25/25/25 fractions, with one rule imposed on
top: the runner ALWAYS keeps at least one contract. The doctrine's own note is explicit
that "the runner keeps the tail that carries the edge" and that the earlier fixed-target
version DESTROYED the edge by capping winners — so at small size the banking is what gets
sacrificed, never the runner.
"""

from app.services.trade_doctrine_engine import TradeDoctrineEngine


class OptionsDynamicTPSEngine:

    def __init__(self, doctrine=None):
        self.doctrine = doctrine or TradeDoctrineEngine()

    # ---- allocation ---------------------------------------------------------
    def allocate(self, contracts):
        """Contracts to sell at each of the 3 targets, plus the runner.

        Returns {"targets": [n1, n2, n3], "runner": n, "bankable": bool, ...}. The runner
        is never zero for a position of at least one contract.
        """
        try:
            contracts = int(contracts)
        except (TypeError, ValueError):
            contracts = 0
        if contracts <= 0:
            return {"targets": [0, 0, 0], "runner": 0, "contracts": 0,
                    "bankable": False, "mode": "NO_POSITION"}

        if contracts == 1:
            # Nothing can be banked. The whole position is the runner and the doctrine is
            # carried entirely by the ratcheting stop.
            return {"targets": [0, 0, 0], "runner": 1, "contracts": 1,
                    "bankable": False, "mode": "RATCHET_ONLY"}

        # Match the doctrine's CUMULATIVE banked fraction, not its per-target fraction.
        #
        # Rounding each 25% slice independently is wrong at small size: at 2 contracts every
        # slice floors to zero and the runner absorbs the whole position, so nothing is ever
        # banked. Matching cumulative share instead asks "how much SHOULD be sold by the
        # time this target is reached" — floor(n x 0.25 / 0.50 / 0.75) — which lands the
        # single bankable contract of a 2-lot at TP2, where the doctrine is also 50% banked,
        # rather than at TP1 where it would be 50% banked against the doctrine's 25%.
        #
        # Flooring also guarantees the runner survives: runner = n - floor(0.75n) >= 1 for
        # any n >= 1, so the tail that carries the edge is structurally protected.
        fractions = list(self.doctrine.SCALE_OUT)                  # (.25, .25, .25)
        runner_fraction = 1.0 - sum(fractions)

        cumulative, running = [], 0.0
        for f in fractions:
            running += f
            cumulative.append(running)                             # .25, .50, .75

        alloc, sold_so_far = [], 0
        for c in cumulative:
            should_be_sold = int(contracts * c)
            alloc.append(max(0, should_be_sold - sold_so_far))
            sold_so_far = should_be_sold
        runner = contracts - sold_so_far

        return {"targets": alloc, "runner": runner, "contracts": contracts,
                "bankable": sum(alloc) > 0,
                "mode": "FULL_LADDER" if contracts >= 4 else "PARTIAL_LADDER",
                "runner_fraction_actual": round(runner / contracts, 4),
                "runner_fraction_doctrine": round(runner_fraction, 4)}

    # ---- plan ---------------------------------------------------------------
    def plan(self, entry_price, direction, atr, contracts):
        """The doctrine's exit plan, with contracts allocated across its exits."""
        base = self.doctrine.exit_plan(entry_price, direction, atr)
        if not base:
            return None
        alloc = self.allocate(contracts)
        base["contracts"] = alloc["contracts"]
        base["contracts_at_target"] = alloc["targets"]
        base["contracts_runner"] = alloc["runner"]
        base["sizing_mode"] = alloc["mode"]
        base["bankable"] = alloc["bankable"]
        base["note_small_size"] = (
            "Position too small to bank at every target. Targets still RATCHET the stop "
            "when reached, so the doctrine's risk profile is intact; only profit-banking "
            "degrades." if alloc["mode"] != "FULL_LADDER" else
            "Full doctrine: banks at all three targets with a runner."
        )
        return base

    # ---- live decision ------------------------------------------------------
    def decide(self, plan, price, targets_filled, extreme_price):
        """What to do right now: how many contracts to sell, and where the stop belongs.

        `targets_filled` counts targets REACHED (not contracts sold) — that distinction is
        the whole point. A target that could not be banked still counts, because it still
        advances the stop.
        """
        if not plan:
            return None
        sign = 1 if plan["direction"] == "LONG" else -1
        targets = plan["targets"]

        newly_reached = 0
        for i in range(targets_filled, len(targets)):
            hit = price >= targets[i] if sign > 0 else price <= targets[i]
            if not hit:
                break
            newly_reached += 1

        filled_after = targets_filled + newly_reached
        at_target = plan.get("contracts_at_target") or [0, 0, 0]
        sell = sum(at_target[i] for i in range(targets_filled, min(filled_after, len(at_target))))

        # The stop advances on targets REACHED, regardless of whether anything was sold.
        stop = self.doctrine.current_stop(plan, filled_after, extreme_price)
        stopped = (price <= stop) if sign > 0 else (price >= stop)

        return {
            "targets_reached": filled_after,
            "sell_contracts": sell,
            "stop": stop,
            "stop_basis": ("INITIAL" if filled_after == 0 else
                           "BREAKEVEN" if filled_after == 1 else
                           "TP1" if filled_after == 2 else "TRAILING_3ATR"),
            "banked_this_step": sell > 0,
            "ratchet_only": newly_reached > 0 and sell == 0,
            "stopped_out": stopped,
            "action": ("CLOSE" if stopped else "SCALE" if sell > 0 else
                       "RATCHET" if newly_reached > 0 else "HOLD"),
        }
