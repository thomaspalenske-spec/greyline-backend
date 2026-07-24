"""Proves the options exit doctrine BEFORE it manages real positions:
- 1-business-day maturity liquidation (never hold to expiry)
- dynamic contract allocation below 4 contracts (runner always survives)
- a full underlying price-path: bank TP1/2/3, ratchet the stop, run the tail, stop out.
"""

from datetime import datetime

from app.services.options_position_manager_engine import OptionsPositionManagerEngine
from app.services.options_dynamic_tps_engine import OptionsDynamicTPSEngine


# ---- 1 business day before expiry ----------------------------------------

def test_prev_business_day_weekend_aware():
    m = OptionsPositionManagerEngine()
    from datetime import date
    # Friday 2026-08-28 -> Thursday 2026-08-27
    assert m._prev_business_day(date(2026, 8, 28)) == date(2026, 8, 27)
    # Monday 2026-08-31 -> Friday 2026-08-28 (skips the weekend)
    assert m._prev_business_day(date(2026, 8, 31)) == date(2026, 8, 28)
    # Sunday -> Friday
    assert m._prev_business_day(date(2026, 8, 30)) == date(2026, 8, 28)


def test_maturity_liquidation_one_business_day_before():
    m = OptionsPositionManagerEngine()
    exp = datetime(2026, 8, 28)          # Friday expiry
    # deadline is Thursday 2026-08-27
    assert m._maturity_liquidation_required(exp, datetime(2026, 8, 20))["required"] is False
    assert m._maturity_liquidation_required(exp, datetime(2026, 8, 26))["required"] is False
    assert m._maturity_liquidation_required(exp, datetime(2026, 8, 27))["required"] is True   # 1 BD before
    assert m._maturity_liquidation_required(exp, datetime(2026, 8, 28))["required"] is True   # expiry day


# ---- dynamic allocation below 4 contracts --------------------------------

def test_allocation_runner_always_survives():
    tps = OptionsDynamicTPSEngine()
    # 1 contract: pure runner, nothing banked
    a1 = tps.allocate(1)
    assert a1["targets"] == [0, 0, 0] and a1["runner"] == 1 and a1["mode"] == "RATCHET_ONLY"
    # 2 & 3 contracts: partial ladder, runner >= 1, never oversells
    for n in (2, 3):
        a = tps.allocate(n)
        assert a["runner"] >= 1
        assert sum(a["targets"]) + a["runner"] == n
        assert a["mode"] == "PARTIAL_LADDER"
    # 4 contracts: full ladder, one at each target + a runner
    a4 = tps.allocate(4)
    assert a4["targets"] == [1, 1, 1] and a4["runner"] == 1 and a4["mode"] == "FULL_LADDER"


# ---- full price path: bank, ratchet, run, stop ---------------------------

def test_doctrine_price_path_four_contracts_banks_and_runs():
    tps = OptionsDynamicTPSEngine()
    # underlying entry 100, ATR 10 -> targets 115/130/145, initial stop 75
    plan = tps.plan(100.0, "LONG", 10.0, 4)
    assert plan["targets"] == [115.0, 130.0, 145.0]
    assert plan["initial_stop"] == 75.0
    assert plan["contracts_at_target"] == [1, 1, 1] and plan["contracts_runner"] == 1

    filled, extreme = 0, 100.0
    # cross TP1
    d = tps.decide(plan, 116.0, filled, max(extreme, 116.0)); extreme = 116.0
    assert d["targets_reached"] == 1 and d["sell_contracts"] == 1 and d["action"] == "SCALE"
    assert d["stop"] == 100.0 and d["stop_basis"] == "BREAKEVEN"   # stop ratcheted to breakeven
    filled = d["targets_reached"]
    # cross TP2
    d = tps.decide(plan, 131.0, filled, max(extreme, 131.0)); extreme = 131.0
    assert d["targets_reached"] == 2 and d["sell_contracts"] == 1 and d["stop"] == 115.0   # stop -> TP1
    filled = d["targets_reached"]
    # cross TP3 -> runner phase, stop now trails
    d = tps.decide(plan, 146.0, filled, max(extreme, 146.0)); extreme = 146.0
    assert d["targets_reached"] == 3 and d["stop_basis"] == "TRAILING_3ATR"
    filled = d["targets_reached"]
    # underlying pulls back into the trailing stop -> CLOSE the runner
    d = tps.decide(plan, 110.0, filled, extreme)
    assert d["action"] == "CLOSE" and d["stopped_out"] is True


def test_doctrine_one_contract_ratchets_then_stops():
    tps = OptionsDynamicTPSEngine()
    plan = tps.plan(100.0, "LONG", 10.0, 1)   # RATCHET_ONLY: whole position is the runner
    # reach TP1: cannot bank (1 contract) but the stop still ratchets -> RATCHET, not SCALE
    d = tps.decide(plan, 116.0, 0, 116.0)
    assert d["action"] == "RATCHET" and d["sell_contracts"] == 0 and d["ratchet_only"] is True
    assert d["stop"] == 100.0   # breakeven — can no longer lose the premium
    # drop below breakeven stop -> CLOSE the single contract
    d = tps.decide(plan, 99.0, 1, 116.0)
    assert d["action"] == "CLOSE" and d["stopped_out"] is True
