import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.trade_doctrine_engine import TradeDoctrineEngine


def test_long_entry_limit_is_below_reference():
    assert TradeDoctrineEngine().entry_limit(100.0, "LONG", 4.0) == 99.0   # 100 - 0.25*4


def test_short_entry_limit_is_above_reference():
    assert TradeDoctrineEngine().entry_limit(100.0, "SHORT", 4.0) == 101.0


def test_long_exit_plan_shape():
    p = TradeDoctrineEngine().exit_plan(entry_price=100.0, direction="LONG", atr=4.0)
    assert p["initial_stop"] == 90.0                         # 100 - 2.5*4
    assert p["targets"] == [106.0, 112.0, 118.0]            # +1.5/3/4.5 ATR
    assert p["scale_out"] == [0.25, 0.25, 0.25]
    assert p["runner_fraction"] == 0.25                     # the uncapped tail
    assert p["runner_trail_atr"] == 3.0


def test_short_exit_plan_is_mirrored():
    p = TradeDoctrineEngine().exit_plan(entry_price=100.0, direction="SHORT", atr=4.0)
    assert p["initial_stop"] == 110.0
    assert p["targets"] == [94.0, 88.0, 82.0]


def test_stop_ratchets_up_the_ladder_then_trails_the_runner():
    eng = TradeDoctrineEngine()
    p = eng.exit_plan(entry_price=100.0, direction="LONG", atr=4.0)
    assert eng.current_stop(p, 0, 100.0) == 90.0            # initial (2.5 ATR)
    assert eng.current_stop(p, 1, 106.0) == 100.0           # breakeven after TP1
    assert eng.current_stop(p, 2, 112.0) == 106.0           # TP1 after TP2
    # runner phase: trails 3 ATR from the extreme, floored at TP2 (112)
    assert eng.current_stop(p, 3, 118.0) == 112.0           # trail 118-12=106 < floor 112 -> floor
    assert eng.current_stop(p, 3, 130.0) == 118.0           # trail 130-12=118 > floor -> trail


def test_runner_stop_never_falls_below_tp2_floor():
    eng = TradeDoctrineEngine()
    p = eng.exit_plan(entry_price=100.0, direction="LONG", atr=4.0)
    # even with a modest extreme, the runner stop can't drop below the banked TP2
    assert eng.current_stop(p, 3, 113.0) == 112.0


def test_unusable_inputs_return_none():
    eng = TradeDoctrineEngine()
    assert eng.entry_limit(0, "LONG", 4.0) is None
    assert eng.exit_plan(100.0, "LONG", 0) is None
