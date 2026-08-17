"""First-real-close watch: pages once per sleeve when it books its first NON-FORCED exit, idempotently.

No real alerts — ExternalAlertEngine.dispatch is monkeypatched to a counter. No court recompute — the
court's sleeves-with-closes are monkeypatched directly.
"""

import app.services.external_alert_engine as eae
from app.services.edge_first_close_watch_engine import EdgeFirstCloseWatchEngine as W


def _patch(monkeypatch, tmp_path, court):
    monkeypatch.setattr(W, "STATE", tmp_path / "edge_first_close_seen.json")
    monkeypatch.setattr(W, "_court_sleeves", lambda self: dict(court))
    calls = []
    monkeypatch.setattr(eae.ExternalAlertEngine, "dispatch",
                        lambda self, title, message, **k: calls.append((title, message, k)) or
                        {"status": "ALERT_DELIVERED_OFF_MACHINE", "reached_off_machine": True})
    return calls


def _sleeve(trades=1, net=42.5, ror=3.1, verdict="ACCUMULATING (1/25 trades — too few to judge)"):
    return {"trades": trades, "total_net_pnl": net, "mean_return_on_risk_pct": ror, "verdict": verdict}


def test_no_closes_pages_nothing(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {})
    r = W().run_cycle()
    assert r["status"] == "EDGE_FIRST_CLOSE_NONE_NEW" and r["paged"] == []
    assert calls == []


def test_first_close_pages_once_and_records(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"trend": _sleeve()})
    r = W().run_cycle()
    assert r["status"] == "EDGE_FIRST_CLOSE_PAGED"
    assert [p["sleeve"] for p in r["paged"]] == ["trend"]
    assert r["first_ever_milestone"] is True
    assert len(calls) == 1
    assert "FIRST-EVER" in calls[0][1]                       # the once-in-a-lifetime milestone wording
    # marker persisted
    assert (tmp_path / "edge_first_close_seen.json").exists()


def test_idempotent_never_repages(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"trend": _sleeve()})
    W().run_cycle()                                          # first page
    r2 = W().run_cycle()                                     # same state again
    assert r2["status"] == "EDGE_FIRST_CLOSE_NONE_NEW"
    assert len(calls) == 1                                   # NOT paged twice


def test_second_sleeve_pages_but_not_first_ever(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"trend": _sleeve()})
    W().run_cycle()                                          # trend recorded (first ever)
    # a second sleeve now has its first close
    monkeypatch.setattr(W, "_court_sleeves",
                        lambda self: {"trend": _sleeve(), "momentum": _sleeve(net=-10.0)})
    r = W().run_cycle()
    assert [p["sleeve"] for p in r["paged"]] == ["momentum"]
    assert r["first_ever_milestone"] is False                # not the first-ever anymore
    assert len(calls) == 2 and "FIRST-EVER" not in calls[1][1]


def test_retired_sleeve_close_does_not_page(monkeypatch, tmp_path):
    """A retired condor sleeve's non-forced close (SIM-mispriced, not a strategy we're proving) must NOT
    trigger the milestone. Regression guard for the premium_earnings false-fire."""
    # patch the court to return the raw sleeves incl. a retired one; _court_sleeves does the filtering
    monkeypatch.setattr(W, "STATE", tmp_path / "seen.json")
    import app.services.edge_persistence_engine as epe
    monkeypatch.setattr(epe.EdgePersistenceEngine, "realized_edge",
                        lambda self: {"sleeves": {"premium_earnings": _sleeve()}})
    calls = []
    monkeypatch.setattr(eae.ExternalAlertEngine, "dispatch",
                        lambda self, *a, **k: calls.append(1) or {"status": "X", "reached_off_machine": False})
    r = W().run_cycle()
    assert r["status"] == "EDGE_FIRST_CLOSE_NONE_NEW" and calls == []


def test_evaluate_is_pure(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"trend": _sleeve()})
    ev = W().evaluate()
    assert ev["newly_first_closed"].get("trend") is not None
    assert ev["any_real_close_ever"] is True
    # pure: no page, no marker written
    assert calls == []
    assert not (tmp_path / "edge_first_close_seen.json").exists()
