"""Per-sleeve edge scorecard: correct instrument attribution, honest 'accumulating' with thin history,
and a decay flag once a sleeve has enough negative days."""

import json

from app.services.edge_persistence_engine import EdgePersistenceEngine as E


def test_attribution_by_instrument():
    assert E._sleeve_of("SVXY", "STOCK") == "carry"
    assert E._sleeve_of("QQQM", "STOCK") == "trend"
    assert E._sleeve_of("SGOV", "STOCK") == "tbill"
    assert E._sleeve_of("IWM 260904C311", "STOCKOPTION") == "premium"
    assert E._sleeve_of("AAPL", "STOCK") == "momentum"


class FakeView:
    def snapshot(self):
        return {"positions": [
            {"symbol": "SVXY", "asset_type": "STOCK", "entry_price": 57.0, "current_price": 58.0,
             "quantity": 20, "unrealized_pnl": 20.0},
            {"symbol": "QQQM", "asset_type": "STOCK", "entry_price": 280.0, "current_price": 279.0,
             "quantity": 1, "unrealized_pnl": -1.0},
        ]}


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "DIR", tmp_path)
    monkeypatch.setattr(E, "LEDGER", tmp_path / "marks.jsonl")
    # keep the realized court hermetic — point it at empty ledgers so it reads no real closed trades
    monkeypatch.setattr(E, "VRP_LEDGER", tmp_path / "vrp.jsonl")
    monkeypatch.setattr(E, "EQ_LEDGER", tmp_path / "eq.jsonl")
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "opt.jsonl")
    monkeypatch.setattr("app.services.broker_account_view_engine.BrokerAccountViewEngine",
                        lambda: FakeView())


def test_snapshot_records_per_sleeve(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    r = E().snapshot()
    assert r["status"] == "EDGE_PERSISTENCE_RECORDED"
    assert r["sleeves"]["carry"] == 20.0 and r["sleeves"]["trend"] == -1.0


def test_open_drift_is_context_never_a_verdict(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    E().snapshot()
    rep = E().report()
    # daily OPEN marks live under open_drift as context — they must NOT carry a verdict
    assert "carry" in rep["open_drift"] and "days_tracked" in rep["open_drift"]["carry"]
    assert "verdict" not in rep["open_drift"]["carry"]
    # the authoritative verdict lives under realized_edge (closed trades only)
    assert "realized_edge" in rep and "method" in rep["realized_edge"]


def test_negative_daily_marks_do_not_fake_a_decay_verdict(monkeypatch, tmp_path):
    """The v1 bug: 12 negative daily open-marks were called 'DECAYED'. But daily marks of the SAME
    held position are autocorrelated (≈1 sample, not 12), so that was false confidence. Now negative
    marks are only context; a decay verdict requires realized CLOSED trades."""
    _patch(monkeypatch, tmp_path)
    led = tmp_path / "marks.jsonl"
    with open(led, "w") as f:
        for i in range(12):
            f.write(json.dumps({"date": f"2026-06-{i+1:02d}", "sleeve": "carry",
                                "unrealized": -5.0, "deployed": 1000.0}) + "\n")
    rep = E().report()
    drift = rep["open_drift"]["carry"]
    assert drift["days_tracked"] == 12 and drift["negative_day_fraction"] == 1.0
    assert "verdict" not in drift                              # no verdict from autocorrelated marks
    assert rep["realized_edge"]["sleeves"] == {}               # court stays silent with 0 closed trades
