"""Expected round-trip EXECUTION cost of a specific contract — the missing input to selection.

Contract selection used to rank by (open interest, delta) and was blind to the spread. That is
how GreyLine came to hold a contract quoted 3.20/4.25 — a 28%-of-mid spread, ~2800 bps of
round-trip cost before it did anything. No amount of smart order pricing rescues that; the fix
is to never SELECT it.

This engine makes round-trip cost a first-class, comparable number so selection can (a) reject
contracts too expensive to trade and (b) prefer the cheapest-to-trade among the rest. Two
components, both in bps of the premium notional:

  spread cost  = the full bid/ask spread as bps of mid. Fair value is the mid; a round trip
                 crosses ~half the spread on entry and half on exit = one full spread. This is a
                 CONSERVATIVE ceiling — our smart limit pricing pays less, and the exit reconciler
                 measures the realised (smaller) number. For a pre-trade gate, the honest ceiling
                 is the right reference.
  fee cost     = round-trip commissions + exchange/regulatory fees (see OptionsFeeModelEngine),
                 which dominate CHEAP contracts and correctly tax lottery tickets.

WHY THIS ALSO BIASES TOWARD ITM (the delta-1 goal, for free): spread-as-%-of-premium is smallest
for tight, liquid, higher-delta strikes and largest for far-OTM. Ranking by cost therefore pulls
selection toward ITM/higher-delta expression on its own — the same conclusion the momentum-reversal
study reached (OTM too costly; trade it closer to delta-1), now enforced at selection time rather
than hoped for.
"""

from os import getenv

from app.services.options_fee_model_engine import OptionsFeeModelEngine


class OptionsExecutionCostEngine:

    # A contract whose expected round-trip cost exceeds this is too expensive to trade, whatever
    # its liquidity or delta. 1200 bps (12%) rejects the disasters (the 28%-wide contract is
    # ~2800) while still admitting normal OTM. Override with GREYLINE_MAX_OPTION_ROUNDTRIP_BPS.
    DEFAULT_MAX_ROUNDTRIP_BPS = 1200.0
    # Cost bucket width for ranking: differences smaller than this are second-order to liquidity,
    # so within a bucket we still prefer the more liquid / better-delta contract.
    COST_BUCKET_BPS = 250.0

    def __init__(self):
        self.fees = OptionsFeeModelEngine()

    @classmethod
    def max_roundtrip_bps(cls):
        try:
            return float(getenv("GREYLINE_MAX_OPTION_ROUNDTRIP_BPS", "") or cls.DEFAULT_MAX_ROUNDTRIP_BPS)
        except (TypeError, ValueError):
            return cls.DEFAULT_MAX_ROUNDTRIP_BPS

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def estimate(self, bid, ask, mid=None, contracts=1):
        """Round-trip cost breakdown in bps of premium. `spread_bps` is None when the quote is
        one-sided/missing (cost unknowable) — callers must treat unknown cost conservatively."""
        bid, ask = self._f(bid), self._f(ask)
        mid = self._f(mid) if mid else (round((bid + ask) / 2, 4) if (bid and ask) else 0.0)
        two_sided = bid > 0 and ask > 0 and ask >= bid
        spread_bps = round((ask - bid) / mid * 10000, 1) if (two_sided and mid > 0) else None
        prem = mid if mid > 0 else (ask or bid)
        fee_bps = self.fees.round_trip_bps(prem, contracts) if prem > 0 else None
        total = None
        if spread_bps is not None and fee_bps is not None:
            total = round(spread_bps + fee_bps, 1)
        return {
            "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2) if mid else None,
            "spread_bps": spread_bps, "fee_bps": fee_bps,
            "total_roundtrip_bps": total,
            "spread_pct_of_mid": round((ask - bid) / mid * 100, 2) if (two_sided and mid > 0) else None,
            "two_sided": two_sided,
        }

    def viable(self, bid, ask, mid=None, contracts=1):
        """True if the contract is cheap enough to trade. Unknown cost (one-sided quote) is NOT
        rejected here — it is deprioritised in ranking instead — because a spotty quote is a data
        gap, not proof of a bad contract; the gate rejects only measured, over-budget cost."""
        est = self.estimate(bid, ask, mid, contracts)
        if est["total_roundtrip_bps"] is None:
            return True, est
        return est["total_roundtrip_bps"] <= self.max_roundtrip_bps(), est

    def rank_bucket(self, bid, ask, mid=None, contracts=1):
        """Lower is cheaper. Unknown cost sorts to the WORST bucket so a real, priced-cheap
        contract always beats one we cannot cost. Used as the PRIMARY selection key."""
        est = self.estimate(bid, ask, mid, contracts)
        total = est["total_roundtrip_bps"]
        if total is None:
            return 10 ** 6                      # unknown cost -> worst
        return int(total // self.COST_BUCKET_BPS)
