"""Pre-fire earnings DRESS REHEARSAL — read-only trace proving the first real earnings condors will build,
validate as sound defined-risk structures, and round-trip into the edge court (premium_earnings). Uses a
mocked dry-run plan so it's deterministic and never touches live UW/broker."""

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine as E


def _condor(sc=105.0, wc=110.0, sp=95.0, wp=90.0, credit=1.0, max_loss=400.0, ror=0.25, qty=1):
    return {"symbol": "ABC", "quantity": qty, "expiration": "2026-08-07", "report_date": "2026-08-03",
            "legs": {"short_call": {"strike": sc, "action": "SELLTOOPEN"},
                     "wing_call": {"strike": wc, "action": "BUYTOOPEN"},
                     "short_put": {"strike": sp, "action": "SELLTOOPEN"},
                     "wing_put": {"strike": wp, "action": "BUYTOOPEN"}},
            "credit_per_condor": credit, "credit_total": credit * 100 * qty,
            "max_loss_total": max_loss, "return_on_risk": ror}


def _prep(monkeypatch, planned, armed=True, skipped=None):
    monkeypatch.setattr(E, "enabled", staticmethod(lambda: armed))
    monkeypatch.setattr(E, "open_positions",
                        lambda self, dry_run=True, limit=None, ignore_arm=False:
                        {"status": "EARNINGS_VOL_DRYRUN", "planned": planned, "planned_count": len(planned),
                         "skipped": skipped or []})
    # keep fire_readiness + candidates cheap/deterministic
    monkeypatch.setattr(E, "fire_readiness",
                        lambda self: {"will_fire": True, "build_verified": False, "verdict": "READY (pending build)"})
    monkeypatch.setattr(E, "_candidates", lambda self, today=None: [{"ticker": "ABC", "report_date": "2026-08-03",
                                                                     "iv_rank": 70, "implied_move_pct": 6.0}])
    # per-condor cap comfortably above the test max_loss
    import app.services.sleeve_capital_budget_engine as scb
    monkeypatch.setattr(scb.SleeveCapitalBudgetEngine, "per_condor_max_loss", classmethod(lambda cls: 500.0))


def test_sound_condor_is_ready_when_armed(monkeypatch):
    _prep(monkeypatch, [_condor()], armed=True)
    r = E().dress_rehearsal()
    assert r["build_go"] is True and r["valid_condors"] == 1 and r["armed"] is True
    assert r["verdict"].startswith("READY TO FIRE")
    row = r["rehearsed"][0]
    assert row["structure_ok"] is True and all(c["ok"] for c in row["checks"])
    proj = row["court_projection"]
    assert proj["sleeve"] == "premium_earnings" and proj["risk_basis"] == "defined_max_loss"
    assert proj["counted_in_court"] is True and proj["max_loss_usd"] == 400.0


def test_sound_condor_but_disarmed_is_build_ok_not_armed(monkeypatch):
    _prep(monkeypatch, [_condor()], armed=False)
    r = E().dress_rehearsal()
    assert r["build_go"] is True and r["armed"] is False
    assert r["verdict"].startswith("BUILD OK, NOT ARMED")
    assert any("DISARMED" in g for g in r["gate_blocks"])


def test_inverted_call_wing_fails_defined_risk(monkeypatch):
    # wing_call BELOW short_call -> not a defined-risk call spread -> structure invalid
    _prep(monkeypatch, [_condor(sc=105.0, wc=100.0)], armed=True)
    r = E().dress_rehearsal()
    assert r["valid_condors"] == 0 and r["build_go"] is False
    checks = {c["check"]: c["ok"] for c in r["rehearsed"][0]["checks"]}
    assert checks["defined_risk_call"] is False


def test_max_loss_over_cap_fails(monkeypatch):
    _prep(monkeypatch, [_condor(max_loss=900.0)], armed=True)   # cap is 500
    r = E().dress_rehearsal()
    checks = {c["check"]: c["ok"] for c in r["rehearsed"][0]["checks"]}
    assert checks["max_loss_bounded"] is False and r["build_go"] is False


def test_zero_credit_fails(monkeypatch):
    _prep(monkeypatch, [_condor(credit=0.0, ror=0.0)], armed=True)
    r = E().dress_rehearsal()
    checks = {c["check"]: c["ok"] for c in r["rehearsed"][0]["checks"]}
    assert checks["credit_positive"] is False


def test_no_condors_built_is_not_ready(monkeypatch):
    _prep(monkeypatch, [], armed=True, skipped=[{"ticker": "ABC", "skip": "credit below floor"}])
    r = E().dress_rehearsal()
    assert r["build_go"] is False and r["planned_count"] == 0
    assert r["verdict"].startswith("NOT READY") and any("0 condors" in g for g in r["gate_blocks"])
    assert r["plan_skipped"] == [{"ticker": "ABC", "skip": "credit below floor"}]


def test_places_nothing_uses_dryrun_ignore_arm(monkeypatch):
    # the rehearsal must call open_positions with dry_run=True AND ignore_arm=True (never a live open)
    seen = {}
    monkeypatch.setattr(E, "enabled", staticmethod(lambda: False))
    monkeypatch.setattr(E, "fire_readiness", lambda self: {"will_fire": False, "verdict": "x"})
    monkeypatch.setattr(E, "_candidates", lambda self, today=None: [])
    def _spy(self, dry_run=True, limit=None, ignore_arm=False):
        seen.update(dry_run=dry_run, ignore_arm=ignore_arm)
        return {"planned": [], "skipped": []}
    monkeypatch.setattr(E, "open_positions", _spy)
    E().dress_rehearsal()
    assert seen == {"dry_run": True, "ignore_arm": True}
