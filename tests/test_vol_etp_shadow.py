"""Long-vol ETP shadow: zero-capital forward-test of long VXX ONLY in backwardation (the regime-conditioned
long-vol leg complementing the SVXY carry sleeve). Hermetic — signal + price monkeypatched, no network."""

import json

from app.services.vol_etp_shadow_engine import VolEtpShadowEngine as V


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "STATE", tmp_path)
    monkeypatch.setattr(V, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(V, "CLOSED", tmp_path / "c.jsonl")


def test_contango_stands_flat(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(V, "_signal", lambda self: {"ok": True, "contango": True, "ratio": 0.92, "state": "CONTANGO_HARVEST"})
    monkeypatch.setattr(V, "_live_price", lambda self, s: 20.0)
    r = V().mark()
    assert not r["cohort_opened"] and "CONTANGO" in r["open_skipped"]     # long-vol leg flat in contango


def test_backwardation_opens_then_settles(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(V, "_signal", lambda self: {"ok": True, "contango": False, "ratio": 1.05, "state": "BACKWARDATION_STAND_ASIDE"})
    monkeypatch.setattr(V, "_live_price", lambda self, s: 20.0)
    r1 = V().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    r2 = V().mark()
    assert not r2["cohort_opened"]                                        # non-overlapping

    o = json.loads((tmp_path / "o.json").read_text())
    o[0]["opened"] = "2020-01-01"
    (tmp_path / "o.json").write_text(json.dumps(o))
    monkeypatch.setattr(V, "_live_price", lambda self, s: 22.0)           # +10%
    r3 = V().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    assert abs(rec["gross_return"] - 0.10) < 1e-6 and rec["net_return"] < rec["gross_return"]


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_VOL_ETP_SHADOW", "false")
    assert V().mark()["status"] == "VOL_ETP_SHADOW_DISABLED"


def test_report_contango_explains_flat(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(V, "_signal", lambda self: {"ok": True, "contango": True, "ratio": 0.9, "state": "CONTANGO_HARVEST"})
    monkeypatch.setattr(V, "_live_price", lambda self, s: 20.0)
    rep = V().report()
    assert rep["cohorts_closed"] == 0 and rep["current_regime"] == "CONTANGO_HARVEST"
    assert "contango" in rep["verdict"].lower()


def test_report_accumulating_on_court_bar(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(V, "_signal", lambda self: {"ok": True, "contango": True, "ratio": 0.9, "state": "CONTANGO_HARVEST"})
    monkeypatch.setattr(V, "_live_price", lambda self, s: None)
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"net_return": 0.02}) for _ in range(3)) + "\n")
    rep = V().report()
    assert rep["cohorts_closed"] == 3 and "accumulating" in rep["verdict"].lower()
    assert rep["rigorous_verdict"]["verdict"].startswith("ACCUMULATING")
