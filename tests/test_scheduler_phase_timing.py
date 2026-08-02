"""Scheduler per-phase timing instrument. Bulletproof checkpoints (append-only, can NEVER break the
trading cycle) record each phase's wall-clock into last_phase_timings, surfaced on /status and in each
recent_cycles entry — so 'which phase dominates the cycle' is data, not a manual profiling session."""

import time

from app.services.background_scheduler_service import BackgroundSchedulerService as S


def test_checkpoints_produce_consecutive_deltas():
    S._phase_reset()
    S._ckpt("phase_a"); time.sleep(0.05)
    S._ckpt("phase_b"); time.sleep(0.02)
    S._ckpt("phase_c")
    t = S._phase_finalize()
    assert set(("phase_a", "phase_b", "phase_c", "_total_instrumented")) <= set(t)
    assert t["phase_b"] >= 0.04                       # the sleep between a and b is attributed to phase_b
    assert t["_total_instrumented"] >= t["phase_b"]


def test_finalize_sets_last_phase_timings():
    S._phase_reset()
    S._ckpt("only")
    S._phase_finalize()
    assert "only" in S._last_phase_timings


def test_ckpt_is_bulletproof_on_bad_state():
    S._phase_marks = None                             # corrupt state
    S._ckpt("x")                                      # must NOT raise (a timing checkpoint can't break the cycle)
    assert S._phase_finalize() == {}                  # degrades to empty, never throws


def test_empty_cycle_finalizes_cleanly():
    S._phase_reset()                                  # start mark only, no phases
    assert S._phase_finalize() == {}                  # a single mark -> no deltas, empty (no crash)


def test_status_exposes_last_phase_timings(monkeypatch):
    # status() must surface last_phase_timings without needing a live cycle
    S._phase_reset(); S._ckpt("pre_sleeve"); S._phase_finalize()
    monkeypatch.setattr(S, "_load_state", classmethod(lambda cls: None))   # don't touch disk state
    st = S.status()
    assert "last_phase_timings" in st and "pre_sleeve" in st["last_phase_timings"]
