"""Index-VRP as a defined-risk iron condor over 24 years. The load-bearing invariant is STRUCTURAL:
the wings cap each trade's loss by construction (the naked strangle does not). Real-data findings locked
against on-disk VIX + SPY (read-only)."""

from pathlib import Path

import pytest

from app.services.index_condor_structure_backtest_engine import IndexCondorStructureBacktestEngine as E
from app.services.index_vrp_history_research_engine import IndexVRPHistoryResearchEngine as H

_ROOT = Path(__file__).resolve().parents[1]
_REAL_VIX = _ROOT / "app" / "data" / "research" / "vol_term_structure" / "VIX.csv"
_REAL_SPY = _ROOT / "app" / "data" / "historical" / "SPY_daily.csv"


def test_bs_prices_are_sane():
    atm_call = E._bs(100, 100, 0.20, 0.08, True)
    atm_put = E._bs(100, 100, 0.20, 0.08, False)
    assert atm_call > 0 and atm_put > 0
    assert abs(atm_call - atm_put) < 1e-6           # r=0 => ATM call == ATM put (put-call parity)
    assert E._bs(100, 130, 0.20, 0.08, True) < atm_call   # further OTM call is cheaper


def test_wings_cap_the_loss_naked_does_not():
    e = E()
    r = e._trade(S=100.0, sigma=0.20, S_T=50.0)      # a -50% crash into expiry
    # the condor loss NEVER exceeds the defined risk known at entry — the wing's whole job
    assert r["condor_pnl"] >= -r["max_loss"] - 1e-6
    assert r["max_loss"] < 15.0                       # bounded to a few % of the 100 spot
    # the naked strangle bleeds far more than the condor's capped loss
    assert r["naked_pnl_pct_spot"] < -20.0
    # calm expiry inside the shorts keeps a positive credit
    calm = e._trade(S=100.0, sigma=0.20, S_T=100.0)
    assert calm["condor_pnl"] > 0


@pytest.mark.skipif(not (_REAL_VIX.exists() and _REAL_SPY.exists()), reason="real VIX/SPY history absent")
def test_real_history_tail_bounded_and_survives_crashes(monkeypatch):
    monkeypatch.setattr(H, "VIX", _REAL_VIX)
    monkeypatch.setattr(H, "SPY", _REAL_SPY)
    r = E().run(save=False)
    assert r["status"] == "ANALYZED" and r["trades"] > 250 and r["span"][0] <= "2003-01-01"
    d = r["defined_risk_condor"]
    # tail BOUNDED: worst month is ~one full max-loss (>= -101%), never a naked blowout
    assert d["worst_month_ror_pct"] >= -101.0
    assert d["skew_monthly"] < -1.0                   # heavy left tail (and Sharpe caveat flags it)
    assert "sharpe_caveat" in d
    # survives crash regimes: net-positive in the large majority of years incl. 2008 and 2020
    yrs = r["ror_pct_by_year"]
    assert yrs["2008"] > 0 and yrs["2020"] > 0
    assert sum(1 for v in yrs.values() if v > 0) >= 0.8 * len(yrs)
    assert r["verdict"].startswith("DEFINED_RISK_HARVEST_SURVIVES")
    assert any("MODELED" in c for c in r["caveats"])   # modeling risk stated, not hidden
