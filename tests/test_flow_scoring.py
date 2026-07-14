import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.institutional_intelligence_engine import InstitutionalIntelligenceEngine as E


# ---- directional score (greek flow / GEX) ----
def test_directional_all_bullish_and_bearish():
    assert E._directional_score([{"f": 10}, {"f": 5}], "f") == 100.0
    assert E._directional_score([{"f": -10}, {"f": -5}], "f") == 0.0


def test_directional_balanced_and_empty():
    assert E._directional_score([{"f": 10}, {"f": -10}], "f") == 50.0
    assert E._directional_score([], "f") == 50.0


def test_directional_partial_imbalance():
    # net +6 of total 10 -> 50 + 50*0.6 = 80
    assert E._directional_score([{"f": 8}, {"f": -2}], "f") == 80.0


def test_directional_missing_field_defaults_50():
    assert E._directional_score([{"other": 1}], "f") == 50.0


# ---- signed premium score (lit / dark prints) ----
def test_signed_premium_bullish_when_above_mid():
    rows = [{"price": 101, "premium": 1000, "nbbo_bid": 99, "nbbo_ask": 101}]  # at ask -> bullish
    assert E._signed_premium_score(rows) == 100.0


def test_signed_premium_bearish_when_below_mid():
    rows = [{"price": 99, "premium": 1000, "nbbo_bid": 99, "nbbo_ask": 101}]  # at bid -> bearish
    assert E._signed_premium_score(rows) == 0.0


def test_signed_premium_balanced_and_empty():
    rows = [
        {"price": 101, "premium": 1000, "nbbo_bid": 99, "nbbo_ask": 101},
        {"price": 99, "premium": 1000, "nbbo_bid": 99, "nbbo_ask": 101},
    ]
    assert E._signed_premium_score(rows) == 50.0
    assert E._signed_premium_score([]) == 50.0


def test_signed_premium_skips_bad_rows():
    rows = [{"price": 0, "premium": 500}, {"price": 100, "premium": 0}]
    assert E._signed_premium_score(rows) == 50.0  # nothing usable
