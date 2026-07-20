import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.options_dynamic_tps_engine import OptionsDynamicTPSEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine

ENGINE = OptionsDynamicTPSEngine()
ENTRY, ATR = 100.0, 4.0          # targets land at 106, 112, 118; initial stop 90


def _plan(contracts):
    return ENGINE.plan(ENTRY, "LONG", ATR, contracts)


# ------------------------------------------------------------------ allocation

def test_four_contracts_reproduce_the_doctrine_exactly():
    a = ENGINE.allocate(4)
    assert a["targets"] == list(map(int, [1, 1, 1]))
    assert a["runner"] == 1
    assert a["mode"] == "FULL_LADDER"


def test_allocation_conserves_contracts_and_never_starves_the_runner():
    """The doctrine's own note says the runner carries the edge and that capping winners
    destroyed it, so at small size the BANKING is sacrificed, never the runner."""
    for n in range(1, 41):
        a = ENGINE.allocate(n)
        assert sum(a["targets"]) + a["runner"] == n, n
        assert a["runner"] >= 1, n


def test_two_contracts_bank_at_tp2_not_tp1():
    """Selling 1 of 2 at TP1 would bank 50% where the doctrine banks 25%. Matching the
    CUMULATIVE fraction puts it at TP2, where the doctrine is also 50% banked."""
    a = ENGINE.allocate(2)
    assert a["targets"] == [0, 1, 0]
    assert a["runner"] == 1


def test_one_contract_banks_nothing_and_is_all_runner():
    a = ENGINE.allocate(1)
    assert a["targets"] == [0, 0, 0]
    assert a["runner"] == 1
    assert a["bankable"] is False
    assert a["mode"] == "RATCHET_ONLY"


def test_zero_or_invalid_contracts_is_not_a_position():
    for bad in (0, -3, None, "x"):
        assert ENGINE.allocate(bad)["mode"] == "NO_POSITION"


# ------------------------------------------------ the ratchet is quantity-independent

def test_single_contract_still_ratchets_to_breakeven_at_tp1():
    """The mission says the first target should recoup the contract's cost. At one contract
    you cannot sell half to get the premium back — but ratcheting the stop to breakeven
    means you can no longer LOSE it. Same intent, expressed through the stop."""
    plan = _plan(1)
    d = ENGINE.decide(plan, price=106.0, targets_filled=0, extreme_price=106.0)
    assert d["targets_reached"] == 1
    assert d["sell_contracts"] == 0          # nothing bankable
    assert d["action"] == "RATCHET"
    assert d["ratchet_only"] is True
    assert d["stop"] == plan["entry_price"]  # breakeven — premium can no longer be lost
    assert d["stop_basis"] == "BREAKEVEN"


def test_single_contract_ratchets_the_full_ladder():
    plan = _plan(1)
    doctrine = TradeDoctrineEngine()
    for reached, expected in [
        (0, plan["initial_stop"]),
        (1, plan["entry_price"]),
        (2, plan["targets"][0]),
    ]:
        assert doctrine.current_stop(plan, reached, ENTRY) == expected
    # in the runner phase the stop trails but can never fall below TP2
    trailing = doctrine.current_stop(plan, 3, extreme_price=130.0)
    assert trailing >= plan["targets"][1]


def test_stop_advances_identically_at_one_and_four_contracts():
    """The whole design claim: risk profile is preserved at any size, only banking degrades."""
    one, four = _plan(1), _plan(4)
    for reached in (0, 1, 2, 3):
        a = ENGINE.decide(one, price=119.0, targets_filled=reached, extreme_price=119.0)
        b = ENGINE.decide(four, price=119.0, targets_filled=reached, extreme_price=119.0)
        assert a["stop"] == b["stop"], reached
        assert a["stop_basis"] == b["stop_basis"], reached


def test_four_contracts_bank_where_one_only_ratchets():
    one, four = _plan(1), _plan(4)
    a = ENGINE.decide(one, price=106.0, targets_filled=0, extreme_price=106.0)
    b = ENGINE.decide(four, price=106.0, targets_filled=0, extreme_price=106.0)
    assert a["sell_contracts"] == 0 and a["action"] == "RATCHET"
    assert b["sell_contracts"] == 1 and b["action"] == "SCALE"


# ------------------------------------------------------------------ live decisions

def test_a_gap_through_several_targets_banks_all_of_them():
    plan = _plan(8)                                   # [2,2,2] + 2 runner
    d = ENGINE.decide(plan, price=119.0, targets_filled=0, extreme_price=119.0)
    assert d["targets_reached"] == 3
    assert d["sell_contracts"] == 6                   # 2+2+2 in one move
    assert d["action"] == "SCALE"


def test_stop_out_closes_regardless_of_size():
    for n in (1, 2, 4, 10):
        plan = _plan(n)
        d = ENGINE.decide(plan, price=89.0, targets_filled=0, extreme_price=100.0)
        assert d["stopped_out"] is True
        assert d["action"] == "CLOSE", n


def test_holding_between_targets_does_nothing():
    plan = _plan(4)
    d = ENGINE.decide(plan, price=104.0, targets_filled=0, extreme_price=104.0)
    assert d["action"] == "HOLD"
    assert d["sell_contracts"] == 0
    assert d["stop"] == plan["initial_stop"]


def test_short_direction_mirrors():
    plan = ENGINE.plan(100.0, "SHORT", ATR, 4)
    assert plan["targets"] == [94.0, 88.0, 82.0]
    d = ENGINE.decide(plan, price=94.0, targets_filled=0, extreme_price=94.0)
    assert d["targets_reached"] == 1 and d["sell_contracts"] == 1
