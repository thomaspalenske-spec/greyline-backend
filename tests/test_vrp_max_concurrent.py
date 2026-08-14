"""GREYLINE_VRP_MAX_CONCURRENT env-tunes the max simultaneously-open condors (scale the live sleeve by
COUNT independently of the dollar risk cap). Hermetic."""

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def test_default_is_class_constant(monkeypatch):
    monkeypatch.delenv("GREYLINE_VRP_MAX_CONCURRENT", raising=False)
    assert V._max_concurrent() == V.MAX_CONCURRENT == 5


def test_env_override(monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_MAX_CONCURRENT", "2")
    assert V._max_concurrent() == 2


def test_bad_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_MAX_CONCURRENT", "not-a-number")
    assert V._max_concurrent() == V.MAX_CONCURRENT
