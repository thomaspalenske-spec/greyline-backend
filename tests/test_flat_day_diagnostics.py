import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.flat_day_diagnostics_engine import FlatDayDiagnosticsEngine


def _write_events(tmp_path, rows):
    p = tmp_path / "master_decision_events.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _qualified_put_demoted_by_regime():
    """A bearish put that met EXECUTE thresholds but was demoted by the directional regime gate."""
    return {
        "timestamp": "2026-07-13T15:00:00",
        "decision": "NO_ACTION",
        "top_candidate": {
            "result": "WATCH",
            "option_type": "PUT",
            "composite_score": 88.0,
            "direction_confidence": 30.0,
            "directional_regime_weak": True,
        },
    }


def test_flat_with_suppressed_signal_names_regime_gate(tmp_path):
    rows = [_qualified_put_demoted_by_regime() for _ in range(10)]
    eng = FlatDayDiagnosticsEngine(lookback_cycles=50)
    eng.EVENTS = _write_events(tmp_path, rows)

    out = eng.diagnose()
    assert out["verdict"] == "FLAT_WITH_SUPPRESSED_SIGNAL"
    assert out["executions"] == 0
    assert out["suppressed_executions"] == 10
    assert out["dominant_suppression_reason"] == "REGIME_GATE_WEAK_DIRECTIONAL"


def test_flat_no_qualified_signal_is_legitimate_discipline(tmp_path):
    # Candidates below EXECUTE thresholds -> flat is correct, not a suppressed signal.
    rows = [{
        "timestamp": "2026-07-13T15:00:00",
        "decision": "NO_ACTION",
        "top_candidate": {"result": "WATCH", "option_type": "CALL",
                          "composite_score": 62.0, "direction_confidence": 40.0},
    } for _ in range(10)]
    eng = FlatDayDiagnosticsEngine(lookback_cycles=50)
    eng.EVENTS = _write_events(tmp_path, rows)

    out = eng.diagnose()
    assert out["verdict"] == "FLAT_NO_QUALIFIED_SIGNAL"
    assert out["suppressed_executions"] == 0


def test_executing_when_trades_fire(tmp_path):
    rows = [{
        "timestamp": "2026-07-13T15:00:00",
        "decision": "EXECUTE",
        "top_candidate": {"result": "EXECUTE", "option_type": "PUT",
                          "composite_score": 90.0, "direction_confidence": 30.0},
    } for _ in range(3)]
    eng = FlatDayDiagnosticsEngine(lookback_cycles=50)
    eng.EVENTS = _write_events(tmp_path, rows)

    out = eng.diagnose()
    assert out["verdict"] == "EXECUTING"
    assert out["executions"] == 3


def test_execute_candidate_blocked_by_exposure_limit_is_suppressed(tmp_path):
    # The 2026-07-14 miss: the candidate cleared scoring as EXECUTE and was refused
    # by the decision layer's sector-exposure circuit breaker. Keying suppression off
    # the candidate's own result reported this as legitimate discipline.
    rows = [{
        "timestamp": "2026-07-14T15:00:00",
        "decision": "NO_ACTION",
        "decision_reason": (
            "Risk state does not allow execution: Hard risk block: "
            "LIMIT_BREACH::MAX_SECTOR_EXPOSURE_PCT (100.0 >= 50.0)"
        ),
        "top_candidate": {"result": "EXECUTE", "option_type": "PUT",
                          "composite_score": 85.97, "direction_confidence": 40.85},
    } for _ in range(10)]
    eng = FlatDayDiagnosticsEngine(lookback_cycles=50)
    eng.EVENTS = _write_events(tmp_path, rows)

    out = eng.diagnose()
    assert out["verdict"] == "FLAT_WITH_SUPPRESSED_SIGNAL"
    assert out["suppressed_executions"] == 10
    assert out["dominant_suppression_reason"] == "EXPOSURE_LIMIT_GATE_SECTOR_CONCENTRATION"


def test_legacy_records_attributed_to_weak_live(tmp_path):
    # Older records (pre-fix) lack directional_regime_weak but carry regime == WEAK_LIVE.
    rows = [{
        "timestamp": "2026-07-13T15:00:00",
        "decision": "NO_ACTION",
        "top_candidate": {"result": "WATCH", "option_type": "PUT",
                          "composite_score": 87.0, "direction_confidence": 25.0,
                          "regime": "WEAK_LIVE"},
    } for _ in range(5)]
    eng = FlatDayDiagnosticsEngine(lookback_cycles=50)
    eng.EVENTS = _write_events(tmp_path, rows)

    out = eng.diagnose()
    assert out["dominant_suppression_reason"] == "REGIME_GATE_WEAK_LIVE_LEGACY"
