"""Scheduler cycle-cost instrumentation: per-phase persistence + steady-state summary.

The /status card shows only the LAST cycle (in-memory), so a persistently-hot phase can't be told
from a one-off spike. These pin the rolling history + the median/p90 summary that makes steady-state
legible. Hermetic — no scheduler cycle actually runs.
"""
import time

from app.services.background_scheduler_service import BackgroundSchedulerService as B


def _fake_cycle(labels_durs):
    B._phase_reset()
    for lbl, dur in labels_durs:
        time.sleep(dur)
        B._ckpt(lbl)
    return B._phase_finalize()


def test_subphases_are_attributed(tmp_path):
    B.CYCLE_COST_HISTORY = tmp_path / "cch.jsonl"
    t = _fake_cycle([("pre_mkt_token_decision", 0.05), ("pre_grade_forward_learn", 0.02),
                     ("pre_institutional_sweep", 0.01), ("pre_institutional_retrain", 0.08),
                     ("pre_sleeve", 0.0)])
    # the old single "pre_sleeve" black box is now split into named sub-phases
    for ph in ("pre_mkt_token_decision", "pre_grade_forward_learn",
               "pre_institutional_sweep", "pre_institutional_retrain"):
        assert ph in t
    assert t["pre_institutional_retrain"] >= t["pre_institutional_sweep"]


def test_persist_and_history_summary(tmp_path):
    B.CYCLE_COST_HISTORY = tmp_path / "cch.jsonl"
    for _ in range(3):
        _fake_cycle([("pre_mkt_token_decision", 0.02), ("pre_institutional_retrain", 0.06)])
        B._persist_cycle_cost(900, "COMPLETE")
    h = B.cycle_cost_history(limit=10)
    assert h["cycles_in_window"] == 3
    # ranked by median cost — the heaviest sub-phase leads
    assert h["phase_cost_ranked_by_median"][0]["phase"] == "pre_institutional_retrain"
    assert h["cycle_seconds"]["median"] == 0.9


def test_history_is_bounded(tmp_path):
    B.CYCLE_COST_HISTORY = tmp_path / "cch.jsonl"
    B._CYCLE_COST_CAP = 5
    for _ in range(12):
        _fake_cycle([("pre_sleeve", 0.001), ("vrp_short_premium", 0.001)])
        B._persist_cycle_cost(10, "COMPLETE")
    lines = [l for l in B.CYCLE_COST_HISTORY.read_text().splitlines() if l.strip()]
    assert len(lines) == 5  # rolling window, not unbounded growth
    B._CYCLE_COST_CAP = 500


def test_persist_is_bulletproof_on_empty(tmp_path):
    B.CYCLE_COST_HISTORY = tmp_path / "cch.jsonl"
    B._phase_reset()
    B._last_phase_timings = {}
    B._persist_cycle_cost(None, "COMPLETE")   # must not raise, must not write a junk row
    assert not B.CYCLE_COST_HISTORY.exists()


def test_history_empty_when_no_file(tmp_path):
    B.CYCLE_COST_HISTORY = tmp_path / "does_not_exist.jsonl"
    h = B.cycle_cost_history()
    assert h["cycles_in_window"] == 0
    assert h["phase_cost_ranked_by_median"] == []
