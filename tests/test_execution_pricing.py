"""Patient pricing posts toward the mid (capturing spread), stays inside the quote, and falls back
to the marketable touch on a bad quote so it never prices worse than crossing."""

from app.services.execution_pricing_engine import ExecutionPricingEngine as X


def test_buy_posts_below_the_ask():
    # bid 100.00 / ask 100.10, aggr 0.35 -> mid 100.05 + 0.35*0.05 = 100.0675 -> 100.07
    assert X.patient_limit(100.00, 100.10, is_buy=True, aggressiveness=0.35) == 100.07


def test_sell_posts_above_the_bid():
    assert X.patient_limit(100.00, 100.10, is_buy=False, aggressiveness=0.35) == 100.03


def test_mid_at_zero_aggr_and_touch_at_one():
    assert X.patient_limit(100.00, 100.10, is_buy=True, aggressiveness=0.0) == 100.05   # mid
    assert X.patient_limit(100.00, 100.10, is_buy=True, aggressiveness=1.0) == 100.10   # ask (marketable)


def test_bad_quote_falls_back_to_touch():
    assert X.patient_limit(0, 100.10, is_buy=True) == 100.10          # no bid -> ask
    assert X.patient_limit(100.20, 100.10, is_buy=True) == 100.10     # crossed -> touch


def test_captured_spread_is_positive_when_patient():
    assert X.spread_saved_bps(100.00, 100.10, aggressiveness=0.35) > 0
    assert X.spread_saved_bps(100.00, 100.10, aggressiveness=1.0) == 0.0   # crossing captures nothing
