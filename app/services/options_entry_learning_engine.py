"""The learning half of the options entry forecaster.

Holds ONE tunable knob — `aggressiveness` in [0,1], where 0 = bid (best price, may never
fill) and 1 = ask (fills like a market order) — and an outcome ledger of every limit-buy
forecast: the quote at the time, the limit we chose, and whether it FILLED and at what price.

THE OBJECTIVE IS COST, NOT FILL RATE. The old controller chased a 70% fill-rate target: below
it, raise aggressiveness; well above it, lower. That optimises the wrong thing. Fill rate is not
what we are trying to maximise — a 95% fill rate achieved by paying most of the spread is worse
than a 60% fill rate achieved near the bid, because for an OTM option the spread paid on entry
is a large fraction of the whole (unproven, thin) edge. Chasing fills just spends that edge to
hit an arbitrary number.

So fill rate is treated as a CONSTRAINT, not the goal: we must fill enough to actually get
positions on (a floor), and SUBJECT TO that floor we minimise the spread paid per entry. The
controller therefore settles at the *lowest* aggressiveness that still clears the fill floor —
the cheapest entries that still deploy capital. The floor is the one explicit judgement here,
and it is defensible: below it the strategy cannot put money to work. The engine already
recorded the cost side (`slippage_vs_mid`); this just makes the loop optimise it.

Honest about maturity: a simple feedback controller that only improves as real fills accumulate,
and it says so in its own stats (`samples`).
"""

import json
from datetime import datetime
from pathlib import Path


class OptionsEntryLearningEngine:

    DIR = Path("app/data/options_entry")
    PARAMS = DIR / "learning_params.json"
    LEDGER = DIR / "entry_outcomes.jsonl"

    DEFAULT_AGGRESSIVENESS = 0.60     # start 60% toward the ask — favor filling while we learn
    MIN_AGGR, MAX_AGGR = 0.30, 1.0
    STEP = 0.05
    # Fill rate is a CONSTRAINT (deploy enough capital), not the objective.
    FILL_RATE_FLOOR = 0.55            # below this we are not getting enough positions on
    FILL_RATE_COMFORT = 0.10          # only trim cost when this far ABOVE the floor, so a step
                                      # down will not immediately breach it
    MIN_COST_FRAC_TO_TRIM = 0.10      # and only when we are actually paying meaningful spread
                                      # (paid > 10% of the spread) — nothing to save near the bid
    TARGET_FILL_RATE = 0.70           # retained for reporting only; NOT the optimisation target
    RECENT_WINDOW = 40                # refine on the last N resolved forecasts
    MIN_SAMPLES_TO_REFINE = 8

    def _load(self):
        try:
            return json.loads(self.PARAMS.read_text())
        except Exception:
            return {"aggressiveness": self.DEFAULT_AGGRESSIVENESS, "updated_at": None,
                    "refine_count": 0, "samples": 0}

    def _save(self, data):
        self.DIR.mkdir(parents=True, exist_ok=True)
        self.PARAMS.write_text(json.dumps(data, indent=2))

    def aggressiveness(self):
        try:
            return float(self._load().get("aggressiveness", self.DEFAULT_AGGRESSIVENESS))
        except (TypeError, ValueError):
            return self.DEFAULT_AGGRESSIVENESS

    # ---- outcome ledger -----------------------------------------------------
    def _read_outcomes(self):
        if not self.LEDGER.exists():
            return []
        out = []
        for line in self.LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def _write_outcomes(self, rows):
        self.DIR.mkdir(parents=True, exist_ok=True)
        self.LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def record_forecast(self, option_symbol, forecast, contracts, order_id, ok=True):
        """Log a just-placed limit forecast as PENDING (awaiting fill)."""
        self.DIR.mkdir(parents=True, exist_ok=True)
        rec = {
            "at": datetime.utcnow().isoformat(),
            "option_symbol": option_symbol,
            "order_id": order_id,
            "contracts": contracts,
            "bid": forecast.get("bid"), "ask": forecast.get("ask"), "mid": forecast.get("mid"),
            "limit_price": forecast.get("limit_price"),
            "aggressiveness": forecast.get("aggressiveness"),
            "status": "PENDING" if ok and order_id else "PLACE_FAILED",
            "fill_price": None, "resolved_at": None,
        }
        with self.LEDGER.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def resolve(self, order_id, filled, fill_price=None):
        """Mark a pending forecast FILLED or UNFILLED once the broker order settles."""
        rows = self._read_outcomes()
        changed = False
        for r in rows:
            if r.get("order_id") == order_id and r.get("status") == "PENDING":
                r["status"] = "FILLED" if filled else "UNFILLED"
                r["fill_price"] = round(float(fill_price), 2) if (filled and fill_price) else None
                r["resolved_at"] = datetime.utcnow().isoformat()
                if filled and fill_price and r.get("mid"):
                    r["slippage_vs_mid"] = round(float(fill_price) - float(r["mid"]), 2)
                changed = True
        if changed:
            self._write_outcomes(rows)
        return changed

    # ---- stats + refinement -------------------------------------------------
    @staticmethod
    def _paid_frac(r):
        """Fraction of the spread actually paid on a fill: 0 = filled at the bid (free), 1 = at
        the ask (full spread paid). This is the COST the objective minimises."""
        try:
            bid, ask, fp = float(r["bid"]), float(r["ask"]), float(r["fill_price"])
        except (TypeError, ValueError, KeyError):
            return None
        if ask <= bid:
            return None
        return max(0.0, min(1.0, (fp - bid) / (ask - bid)))

    def stats(self):
        resolved = [r for r in self._read_outcomes() if r.get("status") in ("FILLED", "UNFILLED")]
        recent = resolved[-self.RECENT_WINDOW:]
        n = len(recent)
        filled = [r for r in recent if r.get("status") == "FILLED"]
        fill_rate = round(len(filled) / n, 3) if n else None
        improvements = [float(r["ask"]) - float(r["fill_price"])
                        for r in filled if r.get("ask") and r.get("fill_price")]
        avg_improvement = round(sum(improvements) / len(improvements), 3) if improvements else None
        # cost side: how much of the spread we actually pay on fills (the thing we minimise)
        paid = [p for p in (self._paid_frac(r) for r in filled) if p is not None]
        avg_paid_frac = round(sum(paid) / len(paid), 3) if paid else None
        paid_abs = [float(r["fill_price"]) - float(r["bid"])
                    for r in filled if r.get("fill_price") and r.get("bid")]
        avg_paid_abs = round(sum(paid_abs) / len(paid_abs), 3) if paid_abs else None
        # cost incurred per ATTEMPT (spread side only; miss penalty is unmodelled and unknown)
        exp_cost = round((fill_rate or 0) * avg_paid_abs, 4) if avg_paid_abs is not None else None
        return {"aggressiveness": self.aggressiveness(), "resolved_samples": n,
                "fill_rate": fill_rate, "avg_price_improvement_vs_ask": avg_improvement,
                "avg_spread_paid_frac": avg_paid_frac, "avg_spread_paid_abs": avg_paid_abs,
                "expected_spread_cost_per_attempt": exp_cost,
                "fill_rate_floor": self.FILL_RATE_FLOOR,
                "target_fill_rate": self.TARGET_FILL_RATE}

    def refine(self):
        """Minimise entry cost SUBJECT TO a fill-rate floor.

        1. Fill rate below the floor  -> raise aggressiveness. The constraint is violated: we are
           not getting enough positions on, so fix that before anything else.
        2. Fill rate comfortably above the floor AND we are paying meaningful spread -> lower
           aggressiveness. We have slack to be more patient and capture a cheaper entry; a single
           step will not breach the floor, and if it does the next cycle raises it back.
        3. Otherwise (near the floor, or already filling cheap) -> hold.

        No-op until enough resolved samples exist."""
        s = self.stats()
        params = self._load()
        aggr = float(params.get("aggressiveness", self.DEFAULT_AGGRESSIVENESS))
        if s["resolved_samples"] < self.MIN_SAMPLES_TO_REFINE or s["fill_rate"] is None:
            params["samples"] = s["resolved_samples"]
            self._save(params)
            return {"changed": False, "reason": "NOT_ENOUGH_SAMPLES", **s}

        fill_rate = s["fill_rate"]
        paid = s["avg_spread_paid_frac"]
        new = aggr
        if fill_rate < self.FILL_RATE_FLOOR:
            new = min(self.MAX_AGGR, aggr + self.STEP)          # below floor -> must fill more
            reason = "BELOW_FILL_FLOOR_RAISED_TO_DEPLOY"
        elif (fill_rate >= self.FILL_RATE_FLOOR + self.FILL_RATE_COMFORT
              and paid is not None and paid > self.MIN_COST_FRAC_TO_TRIM):
            new = max(self.MIN_AGGR, aggr - self.STEP)          # slack + paying spread -> get cheaper
            reason = "TRIMMING_ENTRY_COST_WITHIN_FILL_FLOOR"
        elif fill_rate >= self.FILL_RATE_FLOOR + self.FILL_RATE_COMFORT:
            reason = "FILLS_ALREADY_CHEAP_NO_CHANGE"            # nothing to save near the bid
        else:
            reason = "NEAR_FILL_FLOOR_HOLDING"                  # don't risk breaching the floor

        params.update({"aggressiveness": round(new, 3), "updated_at": datetime.utcnow().isoformat(),
                       "refine_count": int(params.get("refine_count", 0)) + 1,
                       "samples": s["resolved_samples"]})
        self._save(params)
        return {"changed": round(new, 3) != round(aggr, 3), "reason": reason,
                "old_aggressiveness": round(aggr, 3), "new_aggressiveness": round(new, 3), **s}
