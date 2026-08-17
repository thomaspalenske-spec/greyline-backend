"""The return-vs-ruin stress test: the defended book's loss is HARD-CAPPED in any crash; the naked/
levered 'spectacular' config loses multiples of the account. Makes the tradeoff undeniable."""

from app.services.crash_stress_test_engine import CrashStressTestEngine


def test_defended_loss_is_capped_in_every_scenario():
    c = CrashStressTestEngine().compare()
    d = c["DEFENDED (what GreyLine runs)"]
    # every crash, however severe, is bounded by the portfolio cap (-$1200 on a $10k book)
    for r in d["scenarios"]:
        assert r["pnl_usd"] >= -1200.0
        assert r["wiped_out"] is False
    assert d["worst_case_pct_of_book"] == -12.0


def test_spectacular_config_wipes_the_account_in_a_crash():
    c = CrashStressTestEngine().compare()
    s = c["SPECTACULAR (the A+++++++ config)"]
    # unbounded: at least the severe scenarios lose MORE than the whole account
    assert any(r["wiped_out"] for r in s["scenarios"])
    assert s["worst_case_pct_of_book"] < -100.0        # owes money beyond the account
    # and it looks great in the calm year — that's the seduction
    assert s["calm_year_return_pct"] > c["DEFENDED (what GreyLine runs)"]["calm_year_return_pct"]


def test_loss_scales_with_severity_for_the_naked_book():
    e = CrashStressTestEngine()
    mild = e._scenario_pnl(-1500, None, {"index_pct": -0.04, "vol_pts": 20})
    severe = e._scenario_pnl(-1500, None, {"index_pct": -0.20, "vol_pts": 80})
    assert severe < mild < 0     # worse crash -> bigger uncapped loss


def test_live_book_stress_is_bounded_by_the_cap(monkeypatch):
    e = CrashStressTestEngine()
    r = e.stress_current_book()
    for s in r["scenarios"]:
        assert s["pnl_usd"] >= -r["defined_risk_cap_usd"]
