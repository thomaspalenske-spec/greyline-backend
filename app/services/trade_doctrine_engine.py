class TradeDoctrineEngine:
    """
    Stages 3 & 4 of the mission, signal-agnostic: turn a verified directional signal into a
    disciplined trade lifecycle — a limit entry at a strategically sound price, a dynamic
    (trailing) stop, and a profit ladder with an uncapped runner.

    VALIDATED DOCTRINE (MDMP war-game, paired & out-of-sample vs the momentum bridge):
      * wider 2.5-ATR initial stop (a tight stop cut winners on noise),
      * bank 25% at each of three targets (1.5 / 3 / 4.5 ATR),
      * let the final 25% RUN on a 3-ATR trailing (Chandelier) stop.

    This beat a plain hold on mean (4.5x), per-trade Sharpe (3.5x) AND win rate (60% vs
    51%) out-of-sample — the ladder gives consistency, the runner keeps the tail that
    carries the edge. The earlier fixed-four-target doctrine (COA 1) DESTROYED the edge by
    capping winners and stopping on noise; see doctrine_backtest*.py for both.

    Signal-agnostic: takes only {reference_price, direction, atr}, so the same doctrine
    serves the momentum bridge now and institutional flow later. Parameters are the
    validated MDMP values, tunable via the constants below.
    """

    STOP_ATR_MULT = 2.5             # initial stop distance, in ATR
    TARGET_ATRS = (1.5, 3.0, 4.5)  # the three banked targets, in ATR from entry
    SCALE_OUT = (0.25, 0.25, 0.25) # fraction banked at each target; the rest is the runner
    RUNNER_TRAIL_ATR = 3.0         # trailing-stop distance for the runner, in ATR
    ENTRY_PULLBACK_ATR = 0.25      # stage 3: limit this far better than the reference
                                   # (PROVISIONAL — stage-3 entry not yet validated)

    @staticmethod
    def _sign(direction):
        return 1 if str(direction).upper() in ("LONG", "BULLISH", "BUY") else -1

    def entry_limit(self, reference_price, direction, atr):
        """Stage 3: a limit a modest pullback better than the reference (don't chase)."""
        try:
            reference_price, atr = float(reference_price), float(atr)
        except (TypeError, ValueError):
            return None
        if reference_price <= 0 or atr <= 0:
            return None
        sign = self._sign(direction)
        return round(reference_price - sign * self.ENTRY_PULLBACK_ATR * atr, 4)

    def exit_plan(self, entry_price, direction, atr):
        """Stage 4: the validated stop + three-target ladder + trailing runner."""
        try:
            entry_price, atr = float(entry_price), float(atr)
        except (TypeError, ValueError):
            return None
        if entry_price <= 0 or atr <= 0:
            return None
        sign = self._sign(direction)
        targets = [round(entry_price + sign * t * atr, 4) for t in self.TARGET_ATRS]
        return {
            "direction": "LONG" if sign > 0 else "SHORT",
            "entry_price": round(entry_price, 4),
            "atr": round(atr, 6),
            "initial_stop": round(entry_price - sign * self.STOP_ATR_MULT * atr, 4),
            "targets": targets,
            "scale_out": list(self.SCALE_OUT),
            "runner_fraction": round(1.0 - sum(self.SCALE_OUT), 4),
            "runner_trail_atr": self.RUNNER_TRAIL_ATR,
            "doctrine": "2.5-ATR stop; bank 25% at 1.5/3/4.5 ATR; final 25% trails 3 ATR",
        }

    def current_stop(self, plan, targets_filled, extreme_price):
        """The live stop given how many of the 3 targets are filled and the running extreme.

        Ratchets up the ladder (breakeven after TP1, TP1 after TP2, TP2 after TP3), then in
        the runner phase trails from the favorable extreme at RUNNER_TRAIL_ATR, floored at
        TP2 so the runner can never give back below a banked level.
        """
        sign = 1 if plan["direction"] == "LONG" else -1
        if targets_filled <= 0:
            return plan["initial_stop"]
        if targets_filled == 1:
            return plan["entry_price"]                 # breakeven
        if targets_filled == 2:
            return plan["targets"][0]                  # TP1
        trail = extreme_price - sign * plan["runner_trail_atr"] * plan["atr"]
        floor = plan["targets"][1]                     # TP2
        stop = max(floor, trail) if sign > 0 else min(floor, trail)
        return round(stop, 4)
