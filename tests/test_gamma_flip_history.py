"""Daily gamma_flip-vs-spot recorder: stamps the condor proxies' flip/spot each cycle (one row/symbol/day,
last wins) so GATE 2's regime can be TRENDED. Records exactly what the gate sees; never fabricates a regime
from a missing UW read. Hermetic — _gex_map monkeypatched, no network."""

import json

import app.services.index_condor_plan_engine as icp_mod
from app.services.gamma_flip_history_engine import GammaFlipHistoryEngine as G


def _gex(monkeypatch, mapping):
    monkeypatch.setattr(icp_mod.IndexCondorPlanEngine, "_gex_map", lambda self: mapping)


def _seed(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_record_writes_gap_per_symbol(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "DIR", tmp_path)
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _gex(monkeypatch, {"IWM": {"gamma_flip": 344.30, "spot": 302.71, "long_gamma": False},
                       "IBIT": {"gamma_flip": 39.53, "spot": 35.90, "long_gamma": False}})
    r = G().record()
    assert r["status"] == "GAMMA_FLIP_RECORDED"
    assert r["gap_pct"]["IWM"] == round((344.30 - 302.71) / 302.71 * 100, 2)
    rows = [json.loads(x) for x in (tmp_path / "gf.jsonl").read_text().splitlines()]
    assert {x["symbol"] for x in rows} == {"IWM", "IBIT"} and len(rows) == 2


def test_missing_flip_or_spot_is_skipped_never_fabricated(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "DIR", tmp_path)
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _gex(monkeypatch, {"XSP": {"gamma_flip": None, "spot": 600.0, "long_gamma": False},
                       "GLD": {"gamma_flip": 300.0, "spot": 0, "long_gamma": False}})
    assert G().record()["gap_pct"] == {}                 # both dropped, no fabricated regime


def test_record_is_one_row_per_symbol_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "DIR", tmp_path)
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _gex(monkeypatch, {"IWM": {"gamma_flip": 344.0, "spot": 302.0, "long_gamma": False}})
    G().record()
    G().record()                                          # same UTC day -> replaces, not appends
    rows = [x for x in (tmp_path / "gf.jsonl").read_text().splitlines() if x.strip()]
    assert len(rows) == 1


def test_trend_converging(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _seed(tmp_path / "gf.jsonl", [
        {"date": "2026-08-01", "symbol": "IWM", "spot": 300, "gamma_flip": 345, "gap_pct": 15.0, "long_gamma": False},
        {"date": "2026-08-08", "symbol": "IWM", "spot": 302, "gamma_flip": 340, "gap_pct": 12.6, "long_gamma": False},
        {"date": "2026-08-12", "symbol": "IWM", "spot": 303, "gamma_flip": 330, "gap_pct": 8.9, "long_gamma": False}])
    t = G().trend("IWM")["symbols"]["IWM"]
    assert t["sessions"] == 3 and t["first_gap_pct"] == 15.0 and t["last_gap_pct"] == 8.9
    assert "CONVERGING" in t["direction"]


def test_trend_crossed_long_gamma(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _seed(tmp_path / "gf.jsonl", [
        {"date": "2026-08-01", "symbol": "IBIT", "spot": 36, "gamma_flip": 37.8, "gap_pct": 5.0, "long_gamma": False},
        {"date": "2026-08-12", "symbol": "IBIT", "spot": 40, "gamma_flip": 39.5, "gap_pct": -1.2, "long_gamma": True}])
    t = G().trend()["symbols"]["IBIT"]
    assert "CROSSED" in t["direction"] and t["long_gamma"] is True


def test_trend_diverging(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "LEDGER", tmp_path / "gf.jsonl")
    _seed(tmp_path / "gf.jsonl", [
        {"date": "2026-08-01", "symbol": "TLT", "spot": 82, "gamma_flip": 84, "gap_pct": 2.4, "long_gamma": False},
        {"date": "2026-08-12", "symbol": "TLT", "spot": 82, "gamma_flip": 88, "gap_pct": 7.3, "long_gamma": False}])
    assert "DIVERGING" in G().trend("TLT")["symbols"]["TLT"]["direction"]
