"""Forward-shadow VRP proof: day-clustering (same-date closes = one observation), the court's cost-net
condor haircut, sleeve filtering, and that it reaches the SAME rigorous verdict bar as the live court.
Deterministic — the shadow ledger is stubbed. No network, no orders."""

from app.services.condor_shadow_proof_engine import CondorShadowProofEngine as E


def _c(sleeve, d, pnl, max_loss_per, qty=1):
    return {"status": "CLOSED", "sleeve": sleeve, "closed_date": d,
            "realized_pnl": pnl, "max_loss_per": max_loss_per, "quantity": qty}


def test_day_clustering_and_cost_net(monkeypatch):
    closed = [_c("vrp", "2026-08-01", 100, 500), _c("vrp", "2026-08-01", 50, 500),
              _c("vrp", "2026-08-08", 80, 400)]
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    days, rows = E()._day_returns(closed, ("vrp",))
    assert rows == 3 and len(days) == 2                       # two same-date closes collapse to ONE day
    # day1: (150 - 0.03*1000)/1000 = 0.12 ; day2: (80 - 0.03*400)/400 = 0.17
    assert abs(days[0][1] - 0.12) < 1e-9
    assert abs(days[1][1] - 0.17) < 1e-9


def test_earnings_excluded_from_vrp_family(monkeypatch):
    closed = [_c("vrp", "2026-08-01", 100, 500), _c("earnings", "2026-08-01", 999, 500)]
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    _, rows = E()._day_returns(closed, E.VRP_SLEEVES)
    assert rows == 1                                          # only the vrp close counts toward the VRP family


def test_zero_risk_close_skipped(monkeypatch):
    monkeypatch.setattr(E, "_closed", lambda self: [_c("vrp", "2026-08-01", 100, 0)])
    days, rows = E()._day_returns([_c("vrp", "2026-08-01", 100, 0)], ("vrp",))
    assert days == [] and rows == 0


def test_accumulating_when_few(monkeypatch):
    monkeypatch.setattr(E, "_closed", lambda self: [_c("vrp", "2026-08-01", 100, 500)])
    v = E().report()["vrp_family"]
    assert v["independent_days"] == 1
    assert v["verdict"].startswith("ACCUMULATING")
    assert "FORWARD_SHADOW" in v["track"]


def test_reaches_proven_bar_with_enough_positive_days(monkeypatch):
    # 24 distinct days, each a solidly-positive cost-net return-on-risk -> clears the 20-day 95% CI gate
    closed = [_c("vrp", "2026-01-%02d" % (i + 1), 200 if i % 2 else 180, 500) for i in range(24)]
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    v = E().report()["vrp_family"]
    assert v["independent_days"] >= 20
    assert v["verdict"].startswith("PROVEN")


def test_report_structure(monkeypatch):
    monkeypatch.setattr(E, "_closed", lambda self: [_c("vrp", "2026-08-01", 100, 500)])
    r = E().report()
    assert r["status"] == "CONDOR_SHADOW_PROOF"
    assert "vrp_family" in r and set(r["by_sleeve"]) == set(E.VRP_SLEEVES)
