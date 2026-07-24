"""Forecast the 'best' limit-buy price for an option — the educated guess.

Given the contract's live two-sided quote (bid/ask), place the limit a learned fraction of
the spread up from the bid: limit = bid + aggressiveness*(ask-bid). Low aggressiveness buys
cheaper but risks not filling; high aggressiveness fills like a market order. The fraction is
the ONE knob the learning engine refines from real fill outcomes (OptionsEntryLearningEngine).

This is a heuristic that starts sensible and improves with data — not a trained model on day
one. Its only job is to make a defensible guess AND log it so the guess can get better.
"""

from app.services.options_entry_learning_engine import OptionsEntryLearningEngine


class OptionsEntryForecastEngine:

    # Options do NOT all quote in pennies. TradeStation rejected our first live limit orders:
    # "Price = 9.32 not rounded to a valid price increment [0.05]". Rather than hardcode a
    # guess, INFER the increment from the live quote — the exchange only publishes bids/asks
    # on the class's own grid, so the quote is the authority.
    NICKEL, PENNY = 0.05, 0.01

    @classmethod
    def _tick_for(cls, bid, ask):
        """Nickel only when the quote itself proves the class uses it.

        Safe in both directions: a nickel class ALWAYS quotes on the 0.05 grid, so it can
        never be mistaken for a penny class. A penny class whose quote happens to land on
        0.05 gets the coarser tick, which is still a valid multiple of its 0.01 increment.
        """
        on_grid = [p for p in (bid, ask) if p and p > 0]
        if on_grid and all(abs(round(p / cls.NICKEL) * cls.NICKEL - p) < 1e-6 for p in on_grid):
            return cls.NICKEL
        return cls.PENNY

    def __init__(self, learning=None):
        self.learning = learning or OptionsEntryLearningEngine()

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def forecast(self, bid, ask, mid=None, aggressiveness=None):
        bid, ask = self._f(bid), self._f(ask)
        mid = self._f(mid) if mid else (round((bid + ask) / 2, 2) if bid and ask else 0.0)
        aggr = float(aggressiveness) if aggressiveness is not None else self.learning.aggressiveness()

        if bid > 0 and ask > 0 and ask >= bid:
            spread = ask - bid
            raw = bid + aggr * spread
        else:
            # No usable two-sided market — fall back to whatever price we have, marketable.
            raw = ask or mid or bid

        tick = self._tick_for(bid, ask)
        limit = round(round(raw / tick) * tick, 2)
        # Never post below the bid or above the ask.
        if bid > 0:
            limit = max(limit, round(bid, 2))
        if ask > 0:
            limit = min(limit, round(ask, 2))

        two_sided = bid > 0 and ask > 0 and ask >= bid
        return {
            "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2),
            "spread": round(ask - bid, 2) if two_sided else None,
            "aggressiveness": round(aggr, 3),
            "limit_price": limit,
            "improvement_vs_ask": round(ask - limit, 2) if ask > 0 else None,
            "rationale": (
                f"limit {limit:.2f} = bid {bid:.2f} + {aggr:.0%} of {ask-bid:.2f} spread "
                f"({ask-limit:.2f} better than the ask)"
                if two_sided else
                f"no two-sided quote; marketable limit at {limit:.2f}"
            ),
        }
