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


# --- marketable_limit: CROSS the spread for a guaranteed fill (operator directive 2026-08-11) ---

def test_marketable_buy_crosses_to_ask_plus_buffer():
    # ask 100.02, cross 10bps -> 100.02*1.001 = 100.12 (>= ask, marketable)
    lim = X.marketable_limit(99.98, 100.02, is_buy=True, cross_bps=10)
    assert lim >= 100.02 and lim == 100.12


def test_marketable_sell_crosses_to_bid_minus_buffer():
    lim = X.marketable_limit(99.98, 100.02, is_buy=False, cross_bps=10)
    assert lim <= 99.98 and lim == 99.88


def test_marketable_zero_buffer_sits_at_the_touch():
    assert X.marketable_limit(99.98, 100.02, is_buy=True, cross_bps=0) == 100.02   # exactly the ask
    assert X.marketable_limit(99.98, 100.02, is_buy=False, cross_bps=0) == 99.98   # exactly the bid


def test_marketable_rounds_to_penny_grid():
    lim = X.marketable_limit(50.00, 50.013, is_buy=True, cross_bps=0)
    assert lim == 50.01                                    # snapped to the $0.01 grid


def test_marketable_one_sided_quote_falls_back():
    assert X.marketable_limit(0, 100.0, is_buy=False, cross_bps=0) == 100.0    # no bid -> use ask
    assert X.marketable_limit(100.0, 0, is_buy=True, cross_bps=0) == 100.0     # no ask -> use bid


def test_marketable_no_price_returns_none():
    assert X.marketable_limit(0, 0, is_buy=True) is None
