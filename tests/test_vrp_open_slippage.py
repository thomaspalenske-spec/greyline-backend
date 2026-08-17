"""Open-side condor execution slippage: on the first fill reconcile, the plan (decision-mid) credit vs
the ACTUAL fill credit is logged to ExecutionLog once (SELL) — so with the close-side log the premium
sleeves get a FULL round-trip measured execution cost. Fully mocked."""

import json

import app.services.execution_log_engine as el_mod
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _open_condor():
    return {"symbol": "X", "quantity": 1, "status": "OPEN", "expiration": "2026-12-18",
            "credit_per_condor": 0.40, "credit_total": 40.0, "max_loss_total": 460.0,   # PLAN credit
            "legs": [{"symbol": "X 261218C110", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218C115", "action": "BUYTOOPEN"},
                     {"symbol": "X 261218P90", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218P85", "action": "BUYTOOPEN"}]}


# actual fills: shorts received .50, wings paid .35 -> net = (.50+.50)-(.35+.35) = 0.30 actual credit
_FILLS = {"X 261218C110": {"avg": 0.50}, "X 261218C115": {"avg": 0.35},
          "X 261218P90": {"avg": 0.50}, "X 261218P85": {"avg": 0.35}}


def test_reconcile_logs_open_slippage_once(tmp_path, monkeypatch):
    led = tmp_path / "vrp.jsonl"
    led.write_text(json.dumps(_open_condor()) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setattr(V, "_broker_fills", lambda self: _FILLS)
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "LEDGER", tmp_path / "exec.jsonl")
    monkeypatch.setattr(el_mod.ExecutionLogEngine, "DIR", tmp_path)

    V().reconcile_fills(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    assert row["open_slippage_logged"] is True
    assert row["credit_per_condor"] == 0.30                       # reconciled to the actual fill

    recs = [json.loads(l) for l in (tmp_path / "exec.jsonl").read_text().splitlines() if l.strip()]
    op = [x for x in recs if x.get("strategy") == "premium_vrp" and x.get("action") == "SELL"]
    assert len(op) == 1
    assert op[0]["mid"] == 0.40 and round(op[0]["fill_price"], 2) == 0.30   # decision vs actual fill (a cost)

    # idempotent: a second reconcile must NOT log the open slippage again
    V().reconcile_fills(dry_run=False)
    recs2 = [json.loads(l) for l in (tmp_path / "exec.jsonl").read_text().splitlines() if l.strip()]
    assert len([x for x in recs2 if x.get("action") == "SELL"]) == 1
