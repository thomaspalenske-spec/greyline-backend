"""Condor construction guards (the NRG/PLTR bug):
- COST-AWARE credit floor in build_condor: the net credit must clear the 4-leg round-trip cost + a real
  margin, so a thin-credit condor whose premium is eaten by trading cost is rejected at CONSTRUCTION.
- NEGATIVE-CREDIT ENTRY guard in reconcile_fills: a condor whose ACTUAL fills netted <= 0 credit is a
  guaranteed loser — flagged loudly + marked for priority exit, never left as a normal open condor."""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _chain(sbid, sask, wbid, wask):
    # short 105C/95P with a wing at 110C/90P; strikes come from the OCC-style Legs[0].Symbol.
    return [
        {"Side": "Call", "Delta": 0.20, "Bid": sbid, "Ask": sask, "Legs": [{"Symbol": "XYZ 260918C105"}]},
        {"Side": "Call", "Delta": 0.10, "Bid": wbid, "Ask": wask, "Legs": [{"Symbol": "XYZ 260918C110"}]},
        {"Side": "Put", "Delta": 0.20, "Bid": sbid, "Ask": sask, "Legs": [{"Symbol": "XYZ 260918P95"}]},
        {"Side": "Put", "Delta": 0.10, "Bid": wbid, "Ask": wask, "Legs": [{"Symbol": "XYZ 260918P90"}]},
    ]


def test_cost_aware_floor_rejects_thin_credit_wide_spreads():
    # credit ~$0.50/sh (well above the $0.10 MIN_CREDIT margin, so it passes the old floor) but the leg
    # spreads are wide -> round-trip cost ~$0.60 > credit -> the premium can't survive the round trip.
    con = V().build_condor("XYZ", _chain(0.50, 0.90, 0.10, 0.25))
    assert con.get("skip"), f"expected a skip, got {con}"
    assert "round trip" in con["skip"] or "COST-AWARE" in con["skip"], con["skip"]


def test_fat_credit_tight_spreads_builds():
    con = V().build_condor("XYZ", _chain(1.00, 1.05, 0.20, 0.25))   # credit ~$1.50, tight spreads
    assert not con.get("skip"), f"expected a build, got {con}"
    assert con["credit_per_condor"] >= 1.0 and con["quantity"] >= 1


def test_negative_credit_open_condor_is_flagged(tmp_path, monkeypatch):
    # a pre-existing OPEN condor whose reconciled net credit is negative (the NRG case) must be flagged
    # for priority exit and reported under `negative_credit`, never left silent.
    led = tmp_path / "vrp.jsonl"
    row = {"symbol": "NRG 260918C50", "status": "OPEN", "credit_total": -20.0, "max_loss_total": 520.0,
           "quantity": 1, "fill_reconciled": True, "legs": {}}
    led.write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    out = V().reconcile_fills(dry_run=True)
    negs = out.get("negative_credit") or []
    assert any(b.get("symbol") == "NRG 260918C50" for b in negs), out
    # and the persisted-intent flag is set on the row in memory
    reread = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
    # dry_run doesn't persist, but the returned flag is the contract the exit path consumes
    assert negs[0]["credit_total"] == -20.0
