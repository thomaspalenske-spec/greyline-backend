"""Per-contract options fees — small numbers that dominate CHEAP options and were assumed zero.

The cost math treated commissions as "~0". For equities that is roughly true now; for options it
is not. TradeStation charges a per-contract commission and the exchanges/regulators add
pass-through fees on every contract, each way. On a $10k book trading 1-4 contracts, that drag is
real basis points — and, importantly, it is INVERSELY related to premium: a fixed ~$0.65/contract
is trivial on a $12 option (≈11 bps round-trip) but enormous on a $0.40 lottery ticket
(≈325 bps round-trip). Modelling it is what stops the system from mistaking a cheap far-OTM
contract for a cheap TRADE. It is often the opposite.

All-in per-contract fee (commission + exchange + regulatory) is one configurable number, because
the exact split is broker/venue-specific and the total is what matters to the cost model.
"""

from os import getenv


class OptionsFeeModelEngine:

    # TradeStation options run ~$0.50-0.60 commission/contract; exchange + regulatory (ORF, OCC,
    # venue) pass-through adds a few cents. $0.65 all-in is an honest, slightly conservative
    # default. Override with GREYLINE_OPTIONS_FEE_PER_CONTRACT.
    DEFAULT_FEE_PER_CONTRACT = 0.65

    @classmethod
    def fee_per_contract(cls):
        try:
            v = float(getenv("GREYLINE_OPTIONS_FEE_PER_CONTRACT", "") or cls.DEFAULT_FEE_PER_CONTRACT)
            return max(0.0, v)
        except (TypeError, ValueError):
            return cls.DEFAULT_FEE_PER_CONTRACT

    def one_way(self, contracts=1):
        """Dollar fee to open OR close `contracts`."""
        return round(self.fee_per_contract() * max(1, int(contracts or 1)), 2)

    def round_trip(self, contracts=1):
        """Dollar fee to open AND close `contracts` (both sides)."""
        return round(2 * self.one_way(contracts), 2)

    def round_trip_bps(self, premium_per_contract, contracts=1):
        """Round-trip fee as bps of the position's premium notional. This is the units the cost
        model works in — and where cheap options look expensive, correctly."""
        try:
            prem = float(premium_per_contract)
        except (TypeError, ValueError):
            return None
        if prem <= 0:
            return None
        notional = prem * 100 * max(1, int(contracts or 1))     # option premium is x100
        return round(self.round_trip(contracts) / notional * 10000, 1)
