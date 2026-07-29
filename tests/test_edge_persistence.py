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
    monkeypatch.setattr("app.services.broker_account_view_engine.BrokerAccountViewEngine",
                        lambda: FakeView())


def test_snapshot_records_per_sleeve(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    r = E().snapshot()
    assert r["status"] == "EDGE_PERSISTENCE_RECORDED"
    assert r["sleeves"]["carry"] == 20.0 and r["sleeves"]["trend"] == -1.0


def test_report_is_honest_with_thin_history(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    E().snapshot()
    rep = E().report()
    assert "ACCUMULATING" in rep["sleeves"]["carry"]["verdict"]      # 1 day -> not enough to judge


def test_decay_flag_after_enough_negative_days(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    # hand-write 12 days of a persistently-negative sleeve
    led = tmp_path / "marks.jsonl"
    with open(led, "w") as f:
        for i in range(12):
            f.write(json.dumps({"date": f"2026-06-{i+1:02d}", "sleeve": "carry",
                                "unrealized": -5.0, "deployed": 1000.0}) + "\n")
    v = E().report()["sleeves"]["carry"]
    assert v["days_tracked"] == 12 and "DECAYED" in v["verdict"]
