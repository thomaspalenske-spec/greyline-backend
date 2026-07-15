import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine


def _series(mom_up, recent_up, n=260):
    c = [100.0] * n
    c[-253] = 90.0 if mom_up else 110.0
    c[-22] = 100.0
    c[-6] = 99.0 if recent_up else 101.0
    c[-1] = 100.0
    return c


def test_select_only_returns_confirmed_signals():
    # one confirmed (agree), one conflicted (disagree)
    uni = {
        "AAA": _series(mom_up=True, recent_up=False),   # confirmed BULLISH
        "BBB": _series(mom_up=True, recent_up=True),     # conflicted -> excluded
    }
    top, confirmed = MomentumReversalStrategyEngine(top_n=5).select(uni)
    syms = {t["symbol"] for t in top}
    assert "AAA" in syms
    assert "BBB" not in syms
    assert len(confirmed) == 1


def test_select_ranks_by_conviction_and_caps_top_n():
    uni = {}
    # All bullish-momentum + recent-DOWN move (reversal bullish) so all AGREE (confirmed).
    # Stronger momentum (lower anchor) AND larger recent drop -> higher combined rank.
    specs = [(80.0, 96.0), (85.0, 98.0), (92.0, 99.0), (95.0, 99.5)]
    for i, (anchor, five_ago) in enumerate(specs):
        c = [100.0] * 260
        c[-253] = anchor       # 12mo-ago (lower = stronger bullish momentum)
        c[-22] = 100.0
        c[-6] = five_ago       # 5d-ago above? no: five_ago<100 means recent UP. want DOWN.
        c[-1] = 100.0
        c[-6] = 100.0 + (100.0 - five_ago)   # 5d-ago ABOVE 100 -> recent move DOWN -> reversal bullish
        uni[f"S{i}"] = c
    top, confirmed = MomentumReversalStrategyEngine(top_n=2).select(uni)
    assert len(confirmed) == 4
    assert len(top) == 2
    # S0 has both the strongest momentum and the largest recent drop -> top rank on both legs
    assert top[0]["symbol"] == "S0"
    assert top[0]["conviction"] >= top[1]["conviction"]


def test_side_maps_from_bias():
    uni = {"UP": _series(mom_up=True, recent_up=False),
           "DN": _series(mom_up=False, recent_up=True)}
    _, confirmed = MomentumReversalStrategyEngine(top_n=5).select(uni)
    by = {c["symbol"]: c for c in confirmed}
    assert by["UP"]["side"] == "BUY"
    assert by["DN"]["side"] == "SELL"


def test_execution_blocked_when_flag_off(monkeypatch):
    monkeypatch.delenv("GREYLINE_PAPER_EXECUTION_ENABLED", raising=False)
    out = MomentumReversalStrategyEngine().record_paper_trades()
    assert out["recorded"] == 0
    assert out["reason"] == "PAPER_EXECUTION_DISABLED"
