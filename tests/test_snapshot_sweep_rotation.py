import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.institutional.institutional_signal_snapshot_sweep_engine import (
    InstitutionalSignalSnapshotSweepEngine,
)


def _engine(tmp_path, symbols):
    eng = InstitutionalSignalSnapshotSweepEngine.__new__(
        InstitutionalSignalSnapshotSweepEngine)
    eng.CURSOR_PATH = tmp_path / "cursor.json"
    eng.MEMORY_DIR = tmp_path / "memory"
    eng.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    for s in symbols:
        (eng.MEMORY_DIR / f"{s}.jsonl").write_text("{}\n")
    return eng


ALPHABET = ["AAPL", "AMD", "BAC", "CSCO", "DIS", "META", "NVDA", "SPY", "TSLA", "ZZZ"]


def test_every_symbol_is_eventually_collected(tmp_path):
    """The bug this replaces: sorted()[:limit] collected the alphabetically first `limit`
    symbols and everything after them NEVER — which is why SPY had 1 distinct day and AAPL
    had 8 in the dataset the stage-2 verdict was computed from."""
    eng = _engine(tmp_path, ALPHABET)
    seen = set()
    for _ in range(5):
        picked, cursor = eng._rotate(sorted(ALPHABET), 3)
        eng._write_cursor(cursor, len(ALPHABET))
        seen |= set(picked)
    assert seen == set(ALPHABET), sorted(set(ALPHABET) - seen)


def test_late_alphabet_symbols_are_reachable(tmp_path):
    eng = _engine(tmp_path, ALPHABET)
    reached = set()
    for _ in range(4):
        picked, cursor = eng._rotate(sorted(ALPHABET), 3)
        eng._write_cursor(cursor, len(ALPHABET))
        reached |= set(picked)
    assert {"TSLA", "ZZZ", "SPY"} <= reached


def test_rotation_does_not_repeat_within_one_pass(tmp_path):
    eng = _engine(tmp_path, ALPHABET)
    picked_all = []
    for _ in range(len(ALPHABET) // 5):
        picked, cursor = eng._rotate(sorted(ALPHABET), 5)
        eng._write_cursor(cursor, len(ALPHABET))
        picked_all.extend(picked)
    assert len(picked_all) == len(set(picked_all)), "a symbol was sampled twice before all were"


def test_cursor_persists_across_instances(tmp_path):
    eng = _engine(tmp_path, ALPHABET)
    first, cursor = eng._rotate(sorted(ALPHABET), 3)
    eng._write_cursor(cursor, len(ALPHABET))

    fresh = _engine(tmp_path, ALPHABET)          # simulates a process restart
    second, _ = fresh._rotate(sorted(ALPHABET), 3)
    assert set(first) & set(second) == set(), (first, second)


def test_limit_at_or_above_universe_returns_everything(tmp_path):
    eng = _engine(tmp_path, ALPHABET)
    picked, cursor = eng._rotate(sorted(ALPHABET), 50)
    assert sorted(picked) == sorted(ALPHABET)
    assert cursor == 0


def test_empty_universe_and_zero_limit_are_safe(tmp_path):
    eng = _engine(tmp_path, ALPHABET)
    assert eng._rotate([], 10) == ([], 0)
    assert eng._rotate(sorted(ALPHABET), 0) == ([], 0)


def test_cursor_write_failure_never_breaks_the_sweep(tmp_path):
    """An observation sweep must not be taken down by a bookkeeping write."""
    eng = _engine(tmp_path, ALPHABET)
    eng.CURSOR_PATH = Path("/nonexistent-dir-xyz/cursor.json")
    eng._write_cursor(3, 10)          # must not raise
    assert eng._read_cursor() == 0    # unreadable cursor degrades to the start
