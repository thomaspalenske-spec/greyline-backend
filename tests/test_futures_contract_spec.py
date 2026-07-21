import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.futures_contract_spec_engine import FuturesContractSpecEngine

E = FuturesContractSpecEngine()


def test_multiplier_drives_notional_not_one():
    """The core reason equity sizing cannot absorb futures: P&L per point is a multiplier,
    not 1. One /ES at 6000 controls $300k, not one $6000 'share'."""
    assert E.contract_notional("ES", 6000) == 300000.0
    assert E.contract_notional("MES", 6000) == 30000.0
    assert E.contract_notional("CL", 70) == 70000.0


def test_point_pnl_uses_the_multiplier():
    assert E.point_pnl("ES", 1) == 50.0        # one point on /ES = $50
    assert E.point_pnl("MES", 1) == 5.0        # micro = $5
    assert E.point_pnl("CL", 1) == 1000.0      # one dollar of crude = $1,000


def test_ten_k_account_cannot_hold_full_size_index_futures():
    """The honest gate: a $10k book must be told it cannot trade /ES, not silently
    oversized into ~30x its account."""
    for sym in ("ES", "CL", "GC", "NQ", "SI"):
        a = E.affordable(sym, 10000)
        assert a["affordable"] is False, sym
        assert a["status"] == "FUTURES_MARGIN_EXCEEDS_ACCOUNT"
        assert "micro" in a["note"].lower()


def test_ten_k_account_can_hold_micros():
    for sym in ("MES", "MNQ", "MCL", "MGC"):
        a = E.affordable(sym, 10000)
        assert a["affordable"] is True, sym
        assert a["status"] == "FUTURES_AFFORDABLE"


def test_affordable_list_is_micros_and_small_contracts_only():
    aff = set(E.affordable_futures(10000))
    assert {"MES", "MNQ", "MCL", "MGC"} <= aff
    assert "ES" not in aff and "CL" not in aff and "GC" not in aff


def test_a_larger_account_unlocks_full_size_contracts():
    assert E.affordable("ES", 10000)["affordable"] is False
    assert E.affordable("ES", 40000)["affordable"] is True     # ceiling 20k > 13k margin


def test_non_futures_symbol_is_reported_not_guessed():
    a = E.affordable("AAPL", 10000)
    assert a["is_futures"] is False
    assert a["status"] == "NOT_A_FUTURES_CONTRACT"
    assert E.is_futures("AAPL") is False
    assert E.is_futures("@ES") is True         # tolerates the continuous-contract prefix
