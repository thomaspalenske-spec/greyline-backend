import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.directional_signal_engine import DirectionalSignalEngine


def _series(mom_up, recent_up, n=260):
    """Build a close series with a controllable 12-1 momentum sign and 5-day move sign."""
    closes = [100.0] * n
    # 12-1 momentum window is bars [-253 .. -22]. Make the early anchor low/high.
    closes[-253] = 90.0 if mom_up else 110.0   # 12mo-ago price
    closes[-22] = 100.0                          # 1mo-ago price -> mom = up if anchor<now
    # last 5 days: set 5-days-ago price to make the trailing move up or down
    closes[-6] = 99.0 if recent_up else 101.0
    closes[-1] = 100.0
    return closes


def test_confirmed_when_momentum_and_reversal_agree_bullish():
    # momentum up (BULLISH) + recent move DOWN (reversal says BULLISH) -> agree BULLISH
    out = DirectionalSignalEngine().evaluate(_series(mom_up=True, recent_up=False))
    assert out["momentum_bias"] == "BULLISH"
    assert out["reversal_bias"] == "BULLISH"
    assert out["conviction"] == "CONFIRMED"
    assert out["directional_bias"] == "BULLISH"
    assert out["tradeable"] is True


def test_confirmed_when_both_bearish():
    # momentum down (BEARISH) + recent move UP (reversal says BEARISH) -> agree BEARISH
    out = DirectionalSignalEngine().evaluate(_series(mom_up=False, recent_up=True))
    assert out["directional_bias"] == "BEARISH"
    assert out["conviction"] == "CONFIRMED"


def test_conflict_produces_no_trade():
    # momentum up (BULLISH) + recent move UP (reversal says BEARISH) -> conflict
    out = DirectionalSignalEngine().evaluate(_series(mom_up=True, recent_up=True))
    assert out["conviction"] == "CONFLICTED"
    assert out["directional_bias"] is None
    assert out["tradeable"] is False


def test_reversal_fades_not_follows():
    # A recent UP move must make the reversal leg BEARISH (fade), not BULLISH.
    out = DirectionalSignalEngine().evaluate(_series(mom_up=True, recent_up=True))
    assert out["reversal_bias"] == "BEARISH"


def test_insufficient_history_is_honest():
    out = DirectionalSignalEngine().evaluate([100.0] * 100)
    assert out["conviction"] == "INSUFFICIENT_HISTORY"
    assert out["directional_bias"] is None
