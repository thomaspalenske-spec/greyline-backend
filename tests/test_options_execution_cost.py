"""Round-trip execution cost as a first-class selection input: fees (which dominate cheap
options), spread (which dominates wide ones), a gate that rejects untradeable contracts, and a
ranking that prefers the cheapest-to-trade (which pulls toward tighter/ITM strikes)."""

import pytest

from app.services.options_fee_model_engine import OptionsFeeModelEngine
from app.services.options_execution_cost_engine import OptionsExecutionCostEngine


# ---- fees --------------------------------------------------------------------

def test_fee_round_trip_dollars(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPTIONS_FEE_PER_CONTRACT", "0.65")
    f = OptionsFeeModelEngine()
    assert f.one_way(1) == 0.65
    assert f.round_trip(2) == round(2 * 0.65 * 2, 2)


def test_fees_dominate_cheap_options_not_expensive_ones(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPTIONS_FEE_PER_CONTRACT", "0.65")
    f = OptionsFeeModelEngine()
    cheap = f.round_trip_bps(premium_per_contract=0.40)   # $0.40 lottery ticket
    rich = f.round_trip_bps(premium_per_contract=12.00)   # $12 option
    assert cheap > 300 and rich < 30                       # correctly taxes the lottery ticket
    assert cheap > rich * 10


# ---- cost estimate + gate ----------------------------------------------------

def test_wide_otm_contract_is_rejected_by_the_gate(monkeypatch):
    """The 28%-of-mid contract GreyLine actually held (3.20/4.25) must fail the cost gate."""
    monkeypatch.delenv("GREYLINE_MAX_OPTION_ROUNDTRIP_BPS", raising=False)
    c = OptionsExecutionCostEngine()
    ok, est = c.viable(bid=3.20, ask=4.25)
    assert ok is False
    assert est["spread_pct_of_mid"] > 25
    assert est["total_roundtrip_bps"] > 1200


def test_tight_contract_passes_and_costs_little(monkeypatch):
    monkeypatch.delenv("GREYLINE_MAX_OPTION_ROUNDTRIP_BPS", raising=False)
    c = OptionsExecutionCostEngine()
    ok, est = c.viable(bid=5.90, ask=6.10)   # ~3.3% spread
    assert ok is True and est["total_roundtrip_bps"] < 600


def test_unknown_quote_is_not_hard_rejected_but_ranks_worst():
    c = OptionsExecutionCostEngine()
    ok, est = c.viable(bid=0, ask=0)
    assert ok is True and est["total_roundtrip_bps"] is None      # data gap, not a bad contract
    # but it sorts to the worst bucket, so a real priced-cheap contract always beats it
    assert c.rank_bucket(0, 0) > c.rank_bucket(5.90, 6.10)


def test_cheaper_to_trade_contract_ranks_ahead():
    c = OptionsExecutionCostEngine()
    tight = c.rank_bucket(5.90, 6.10)     # ~3% spread
    wide = c.rank_bucket(3.20, 4.25)      # ~28% spread
    assert tight < wide                    # lower bucket = cheaper = selected first
