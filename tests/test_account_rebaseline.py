"""Re-baseline to $10k: zero the realized ledger WITHOUT destroying the loss history.

Guards: the prior ledger is archived (not deleted), realized reads 0 after, the legacy backfill can
never be re-injected once re-baselined, lingering OPEN VRP rows are marked CLOSED, and it runs once.
"""

import json

from app.services.account_rebaseline_engine import AccountRebaselineEngine
from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine as MR


def _paths(monkeypatch, tmp_path):
    monkeypatch.setattr(MR, "DIR", tmp_path)
    monkeypatch.setattr(MR, "LEDGER", tmp_path / "realized.jsonl")
    monkeypatch.setattr(MR, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(MR, "_broker_daily_realized", lambda self: -8.0)
    monkeypatch.setattr(AccountRebaselineEngine, "MARKER", tmp_path / "rebaseline_marker.json")
    monkeypatch.setattr(AccountRebaselineEngine, "VRP_LEDGER", tmp_path / "vrp.jsonl")
    monkeypatch.setattr(AccountRebaselineEngine, "EQUITY_LEDGER", tmp_path / "equity.jsonl")


def test_rebaseline_zeroes_but_archives(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    mr = MR()
    mr.ensure_legacy_backfill()                       # -4101.63 on the ledger
    assert mr.cumulative_realized() == round(MR.LEGACY_BACKFILL_USD, 2)

    res = AccountRebaselineEngine().rebaseline()
    assert res["status"] == "REBASELINED"
    assert mr.cumulative_realized() == 0.0            # fresh line
    assert res["archived_realized_before"] == round(MR.LEGACY_BACKFILL_USD, 2)
    # the loss history is preserved in the archive, not deleted
    assert res["archived_to"] and json.loads(open(res["archived_to"]).read().splitlines()[0])["amount"] \
        == round(MR.LEGACY_BACKFILL_USD, 2)
    # daily baseline reset to the broker's current daily so today's realized isn't re-booked
    assert json.loads((tmp_path / "state.json").read_text())["booked_today"] == -8.0


def test_legacy_backfill_cannot_return_after_rebaseline(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    AccountRebaselineEngine().rebaseline()
    # marker present -> ensure_legacy_backfill must NOT re-inject the archived loss
    assert MR().ensure_legacy_backfill()["status"] == "SKIPPED_REBASELINED"
    assert MR().cumulative_realized() == 0.0


def test_runs_once_per_arming(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    e = AccountRebaselineEngine()
    assert e.rebaseline_if_pending()["status"] == "REBASELINED"
    assert e.rebaseline_if_pending()["status"] == "REBASELINE_ALREADY_DONE"
    assert e.arm()["status"] == "REBASELINE_ARMED"
    assert e.rebaseline_if_pending()["status"] == "REBASELINED"


def test_open_vrp_rows_marked_closed(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    vrp = tmp_path / "vrp.jsonl"
    vrp.write_text(json.dumps({"symbol": "IWM", "status": "OPEN", "legs": []}) + "\n"
                   + json.dumps({"symbol": "SPY", "status": "CLOSED", "legs": []}) + "\n")
    res = AccountRebaselineEngine().rebaseline()
    assert res["vrp_ledger_rows_closed"] == 1
    rows = [json.loads(l) for l in vrp.read_text().splitlines() if l.strip()]
    assert all(r["status"] == "CLOSED" for r in rows)
    assert any(r.get("close_reason") == "CLEAN_SLATE_FLATTEN" for r in rows)


def test_open_equity_rows_marked_closed_at_zero_realized(monkeypatch, tmp_path):
    """The clean-slate flatten sells every equity position at the broker; the per-trade ledger rows must
    be reconciled to CLOSED (else the reality guard flags them as phantoms). Realized is booked 0 — the
    flatten's real fills already moved the broker-daily the baseline snaps to; re-deriving from stale entry
    prices would double-count. Regression guard for the 2026-08-04 equity-phantom bug."""
    _paths(monkeypatch, tmp_path)
    eq = tmp_path / "equity.jsonl"
    eq.write_text(json.dumps({"symbol": "AMKR", "status": "OPEN", "entry_price": 50.5, "quantity": 4}) + "\n"
                  + json.dumps({"symbol": "GLW", "status": "OPEN", "entry_price": 142.2, "quantity": 1}) + "\n"
                  + json.dumps({"symbol": "OLD", "status": "CLOSED", "entry_price": 10.0, "quantity": 1}) + "\n")
    res = AccountRebaselineEngine().rebaseline()
    assert res["equity_ledger_rows_closed"] == 2
    rows = [json.loads(l) for l in eq.read_text().splitlines() if l.strip()]
    assert all(r["status"] == "CLOSED" for r in rows)
    reconciled = [r for r in rows if r.get("close_reason") == "CLEAN_SLATE_FLATTEN"]
    assert len(reconciled) == 2
    assert all(r["realized_pnl"] == 0.0 for r in reconciled)   # no fabricated P&L
