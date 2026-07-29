"""Patient execution pricing — capture part of the spread instead of always crossing it.

The retail execution ceiling is real: GreyLine can't be the liquidity, can't earn maker rebates,
can't co-locate. But it does NOT have to pay the FULL spread on every trade the way a naive
marketable order does. Almost none of the sleeve trades are urgent (trend is a slow signal, carry
rebalances gradually, the T-bill sweep parks idle cash) — so they can post TOWARD THE MID and
capture most of the spread, crossing only what's needed to still get filled.

`aggressiveness` in [0,1]: 0 = post at the mid (capture the whole half-spread, lower fill odds),
1 = marketable at the touch (the old behavior, pay the whole half-spread). Default 0.35 pays ~35%
of the half-spread and keeps fill odds high. Failure mode is benign: an unfilled patient limit just
gets re-evaluated next cycle against the live book, never a broken order.
"""

from os import getenv


class ExecutionPricingEngine:

    DEFAULT_AGGRESSIVENESS = 0.35

    @classmethod
    def _aggr(cls):
        try:
            a = float(getenv("GREYLINE_EXEC_AGGRESSIVENESS", "") or cls.DEFAULT_AGGRESSIVENESS)
        except (TypeError, ValueError):
            a = cls.DEFAULT_AGGRESSIVENESS
        return min(1.0, max(0.0, a))

    @classmethod
    def patient_limit(cls, bid, ask, is_buy, tick=0.01, aggressiveness=None):
        """A limit posted `aggressiveness` of the way from the mid toward the touch.

        Falls back to the marketable touch if the quote is unusable (missing side / crossed / <=0),
        so it never prices worse than the old behavior on a bad quote."""
        try:
            bid = float(bid); ask = float(ask)
        except (TypeError, ValueError):
            bid, ask = 0.0, 0.0
        if bid <= 0 or ask <= 0 or ask < bid:
            # no reliable spread to work inside -> marketable at whatever touch we have
            touch = ask if is_buy else bid
            return round(touch, 2) if touch and touch > 0 else None
        a = cls._aggr() if aggressiveness is None else min(1.0, max(0.0, aggressiveness))
        mid = (bid + ask) / 2.0
        px = mid + a * (ask - mid) if is_buy else mid - a * (mid - bid)
        t = tick if tick and tick > 0 else 0.01
        return round(round(px / t) * t, 2)

    @classmethod
    def spread_saved_bps(cls, bid, ask, aggressiveness=None):
        """How much of the round-trip spread this pricing captures vs. always crossing (for logging)."""
        try:
            bid = float(bid); ask = float(ask)
            if bid <= 0 or ask <= 0 or ask < bid:
                return 0.0
            a = cls._aggr() if aggressiveness is None else aggressiveness
            mid = (bid + ask) / 2.0
            return round((1 - a) * (ask - bid) / mid * 1e4, 1)     # captured fraction of the spread
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0
