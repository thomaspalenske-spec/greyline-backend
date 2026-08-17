import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.flow_skill_validation_engine import FlowSkillValidationEngine

MOD = "app.services.flow_skill_validation_engine"


def _write_snapshots(mem_dir, symbol, rows):
    p = mem_dir / f"{symbol}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _snap(symbol, ts, buying, selling):
    return {"symbol": symbol, "timestamp": ts, "snapshot": {
        "symbol": symbol, "institutional_buying_score": buying, "institutional_selling_score": selling}}


def test_constant_signal_flagged_as_data_quality(tmp_path):
    # buying=100/selling=0 constant -> one-sided, no real signal
    eng = FlowSkillValidationEngine(horizon_hours=24)
    eng.memory_dir = tmp_path / "mem"
    eng.ledger = tmp_path / "nope.jsonl"
    _write_snapshots(eng.memory_dir, "NVDA", [
        _snap("NVDA", "2026-07-01T10:00:00", 100, 0),
        _snap("NVDA", "2026-07-01T11:00:00", 100, 0),
    ])
    # Simulate no UW key by patching the ACTUAL source validate() reads (env_reload.uw_api_key) — patching
    # this module's getenv doesn't reach it, and the real .env has a key, so the warning never fired.
    with patch("app.services.env_reload.uw_api_key", return_value=""):
        r = eng.validate()
    assert any("CONSTANT_OR_ONE_SIDED" in w for w in r["data_quality_warnings"])
    assert any("KEY_NOT_CONFIGURED" in w for w in r["data_quality_warnings"])


def test_real_varying_flow_with_prices_yields_mcc(tmp_path):
    eng = FlowSkillValidationEngine(horizon_hours=24, tolerance_hours=6)
    eng.memory_dir = tmp_path / "mem"
    eng.ledger = tmp_path / "ledger.jsonl"
    # price ledger: AAA rises 100->110 over the day; BBB falls 100->90
    with open(eng.ledger, "w") as f:
        for row in [
            {"symbol": "AAA", "snapshot_price": 100, "timestamp": "2026-07-01T10:00:00"},
            {"symbol": "AAA", "snapshot_price": 110, "timestamp": "2026-07-02T10:00:00"},
            {"symbol": "BBB", "snapshot_price": 100, "timestamp": "2026-07-01T10:00:00"},
            {"symbol": "BBB", "snapshot_price": 90, "timestamp": "2026-07-02T10:00:00"},
        ]:
            f.write(json.dumps(row) + "\n")
    # flow: AAA net buying (predicts up, correct); BBB net selling (predicts down, correct)
    _write_snapshots(eng.memory_dir, "AAA", [_snap("AAA", "2026-07-01T10:00:00", 80, 20)])
    _write_snapshots(eng.memory_dir, "BBB", [_snap("BBB", "2026-07-01T10:00:00", 20, 80)])

    with patch(f"{MOD}.getenv", return_value="key"):
        r = eng.validate()
    assert r["usable_graded"] == 2
    # both predictions correct -> favorable both; skill engine handles small-n verdict
    assert len(r["data_quality_warnings"]) == 0


def test_no_price_join_dropped(tmp_path):
    eng = FlowSkillValidationEngine(horizon_hours=24)
    eng.memory_dir = tmp_path / "mem"
    eng.ledger = tmp_path / "empty.jsonl"
    _write_snapshots(eng.memory_dir, "AAA", [_snap("AAA", "2026-07-01T10:00:00", 80, 20)])
    with patch(f"{MOD}.getenv", return_value="key"):
        r = eng.validate()
    assert r["usable_graded"] == 0
    assert r["dropped_no_price_join"] == 1
