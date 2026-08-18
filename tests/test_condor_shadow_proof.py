"""Forward-shadow VRP proof: day-clustering (same-date closes = one observation), the court's cost-net
condor haircut, sleeve filtering, and that it reaches the SAME rigorous verdict bar as the live court.
Deterministic — the shadow ledger is stubbed. No network, no orders."""

from app.services.condor_shadow_proof_engine import CondorShadowProofEngine as E


def _c(sleeve, d, pnl, max_loss_per, qty=1, symbol="SPY"):
    # symbol defaults to an eligible LIQUID_ETF so vrp-sleeve rows pass the live-universe filter
    return {"status": "CLOSED", "sleeve": sleeve, "closed_date": d, "symbol": symbol,
            "realized_pnl": pnl, "max_loss_per": max_loss_per, "quantity": qty}


def test_day_clustering_and_cost_net(monkeypatch):
    closed = [_c("vrp", "2026-08-01", 100, 500), _c("vrp", "2026-08-01", 50, 500),
              _c("vrp", "2026-08-08", 80, 400)]
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    days, rows, _ = E()._day_returns(closed, ("vrp",))
    assert rows == 3 and len(days) == 2                       # two same-date closes collapse to ONE day
    # day1: (150 - 0.03*1000)/1000 = 0.12 ; day2: (80 - 0.03*400)/400 = 0.17
    assert abs(days[0][1] - 0.12) < 1e-9
    assert abs(days[1][1] - 0.17) < 1e-9


def test_earnings_excluded_from_vrp_family(monkeypatch):
    closed = [_c("vrp", "2026-08-01", 100, 500), _c("earnings", "2026-08-01", 999, 500)]
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    _, rows, _ = E()._day_returns(closed, E.VRP_SLEEVES)
    assert rows == 1                                          # only the vrp close counts toward the VRP family


def test_zero_risk_close_skipped(monkeypatch):
    monkeypatch.setattr(E, "_closed", lambda self: [_c("vrp", "2026-08-01", 100, 0)])
    days, rows, _ = E()._day_returns([_c("vrp", "2026-08-01", 100, 0)], ("vrp",))
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


def _legs(sc, wc, sp, wp):
    # each tuple is (bid, ask); spread = ask-bid
    return {"short_call": {"bid": sc[0], "ask": sc[1]}, "wing_call": {"bid": wc[0], "ask": wc[1]},
            "short_put": {"bid": sp[0], "ask": sp[1]}, "wing_put": {"bid": wp[0], "ask": wp[1]}}


def test_real_spread_cost_used_when_legs_present(monkeypatch):
    # spreads: 0.56 + 0.34 + 0.30 + 0.26 = 1.46 -> half = 0.73 -> cost = $73 (qty 1); NOT the flat 3% ($6.75)
    e = _c("vrp", "2026-08-01", 100, 225, 1)
    e["legs"] = _legs((1.39, 1.95), (1.14, 1.48), (3.15, 3.45), (2.55, 2.81))
    monkeypatch.setattr(E, "_closed", lambda self: [e])
    cost, had = E()._close_cost(e)
    assert had is True and abs(cost - 73.0) < 1e-6
    days, _, _ = E()._day_returns([e], ("vrp",))
    # net = 100 - 73 = 27 ; risk 225 -> 0.12 (a flat-3% haircut would give (100-6.75)/225 = 0.414)
    assert abs(days[0][1] - (27.0 / 225.0)) < 1e-9


def test_cost_validation_flags_the_gap(monkeypatch):
    e = _c("vrp", "2026-08-01", 100, 225, 1)
    e["legs"] = _legs((1.39, 1.95), (1.14, 1.48), (3.15, 3.45), (2.55, 2.81))
    monkeypatch.setattr(E, "_closed", lambda self: [e])
    cv = E().cost_validation()
    assert cv["court_flat_haircut_pct"] == 3.0
    # 73 / 225 = 32.4% — an order of magnitude above the flat haircut
    assert cv["measured_by_sleeve"]["vrp"]["median_pct"] > 25.0


def test_report_structure(monkeypatch):
    monkeypatch.setattr(E, "_closed", lambda self: [_c("vrp", "2026-08-01", 100, 500)])
    r = E().report()
    assert r["status"] == "CONDOR_SHADOW_PROOF"
    assert "vrp_family" in r and set(r["by_sleeve"]) == set(E.VRP_SLEEVES)


def test_single_name_excluded_from_vrp_verdict(monkeypatch):
    # the live 'vrp' sleeve is ETF-only (single-name condors retired as cost-eaten); a legacy single-name
    # close (CRCL) must NOT count toward the forward verdict, while an eligible ETF (SPY) does.
    closed = [_c("vrp", "2026-08-01", 100, 500, symbol="SPY"),
              _c("vrp", "2026-08-02", 999, 500, symbol="CRCL")]   # single name, not in LIQUID_ETFS
    monkeypatch.setattr(E, "_closed", lambda self: closed)
    days, rows, excluded = E()._day_returns(closed, ("vrp",))
    assert rows == 1 and excluded == 1               # only SPY counts; CRCL excluded
    assert len(days) == 1
