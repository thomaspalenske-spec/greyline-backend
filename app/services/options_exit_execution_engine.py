"""Price an option EXIT the way the entry is priced — never a naked market order.

The entry side already does the right thing: it places a LIMIT a learned fraction of the spread
up from the bid, and a learning loop tunes it. The exit side did the opposite — every
SELLTOCLOSE went out as `order_type="Market"`. On an OTM option that is the single most
expensive habit in the whole book:

  * A market SELL hits the BID, and on a wide OTM contract the bid can sit 10-30% below mid.
  * Worse, a market order has NO price floor: on a thin option book it can sweep through the
    bid and fill at a genuinely absurd price. Every real options desk forbids naked option
    market orders for exactly this reason.
  * And it happens on EVERY tranche of the 4-TP ladder, so the smart-entry saving is handed
    straight back on the way out.

So this engine prices the exit as a LIMIT, tiered by how urgently the position must leave:

  PATIENT  — a take-profit tranche. The position is a WINNER; there is no reason to pay the
             spread to get out. Rest the limit near the ASK and let the market come to us. If it
             does not fill this cycle, nothing bad happens — we still hold a winner and reprice
             next cycle. This is where spread is captured rather than paid.

  URGENT   — a stop-loss or a maturity liquidation. We MUST be out. But "must be out" is not the
             same as "accept any price": a MARKETABLE LIMIT at the bid fills against the resting
             bid immediately, just like a market order would at the top of book, while capping
             the fill at the bid so a thin book cannot fill us through it. Same urgency, with a
             floor. Only when there is no usable two-sided quote at all does an urgent exit fall
             back to a true market order — and that fallback is flagged, never silent.

  (A PATIENT exit with no usable quote is SKIPPED, not market-dumped — we never blind-sell a
  winner. It simply retries next cycle when a quote returns.)

The tick grid is inferred from the live quote (nickel vs penny), reusing the entry forecaster's
logic, because posting an off-grid option price gets rejected by TradeStation.
"""

from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine


class OptionsExitExecutionEngine:

    # For a SELL, rest the limit this fraction of the spread DOWN from the ask. Small fraction =
    # close to the ask = most spread captured, lower fill odds; the doctrine escalates a tranche
    # to URGENT if it ever truly must leave, so patience here is cheap.
    PATIENT_FRAC_FROM_ASK = 0.25

    # Reasons that mean "get out now". Substring match against the exit reason string the
    # position manager passes (OPTIONS_DOCTRINE_STOP, OPTIONS_MATURITY_1_BUSINESS_DAY, ...).
    URGENT_MARKERS = ("STOP", "MATUR", "LIQUID", "TRAIL", "EXPIR")

    @classmethod
    def classify(cls, reason):
        r = str(reason or "").upper()
        return "urgent" if any(m in r for m in cls.URGENT_MARKERS) else "patient"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def price_exit(self, bid, ask, reason, urgency=None):
        """Decide order_type + limit_price for a SELLTOCLOSE.

        Returns a dict:
          {order_type: 'Limit'|'Market', limit_price: float|None, urgency, forced_market: bool,
           skip: bool, mid, tick, rationale}
        `skip=True` means: do not place an order this cycle (patient exit, no usable quote).
        """
        bid, ask = self._f(bid), self._f(ask)
        urgency = urgency or self.classify(reason)
        two_sided = bid > 0 and ask > 0 and ask >= bid
        mid = round((bid + ask) / 2, 4) if two_sided else (bid or ask or 0.0)

        if not two_sided:
            if urgency == "urgent":
                return {"order_type": "Market", "limit_price": None, "urgency": urgency,
                        "forced_market": True, "skip": False, "mid": mid or None, "tick": None,
                        "rationale": ("no two-sided quote and the exit is urgent (stop/maturity) "
                                      "— forced to market to guarantee we leave; flagged")}
            return {"order_type": None, "limit_price": None, "urgency": urgency,
                    "forced_market": False, "skip": True, "mid": mid or None, "tick": None,
                    "rationale": ("no two-sided quote on a take-profit tranche — SKIP rather than "
                                  "blind-sell a winner at market; retry next cycle")}

        tick = OptionsEntryForecastEngine._tick_for(bid, ask)
        spread = ask - bid

        if urgency == "urgent":
            # Marketable at the bid: fills immediately against resting bid liquidity, but the bid
            # is a hard floor — a thin book cannot fill us through it the way a market order can.
            limit = round(bid, 2)
            rationale = ("urgent exit priced as a MARKETABLE LIMIT at the bid — fills like a "
                         "market order at top of book, but the bid is a floor against a thin book")
        else:
            # Patient: post near the ask, capture the spread, willing to wait / miss a tranche.
            raw = ask - self.PATIENT_FRAC_FROM_ASK * spread
            limit = round(round(raw / tick) * tick, 2)
            limit = min(max(limit, round(bid, 2)), round(ask, 2))   # stay inside the quote
            rationale = (f"patient take-profit priced {self.PATIENT_FRAC_FROM_ASK:.0%} of the "
                         f"spread below the ask to capture spread instead of paying it")

        return {"order_type": "Limit", "limit_price": limit, "urgency": urgency,
                "forced_market": False, "skip": False, "mid": round(mid, 2), "tick": tick,
                "spread": round(spread, 2), "rationale": rationale}
