"""Gated total-return wiring of the momentum signal: flag OFF reads price-only close (unchanged legacy
behavior), flag ON reads dividend-adjusted adj_close, with a price-only FALLBACK when the total-return file
is missing. Deterministic tmp fixtures — no real data, no network, no orders."""

import pytest

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine as MR


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    hist = tmp_path / "historical"; tr = tmp_path / "tr"
    hist.mkdir(); tr.mkdir()
    # FOO: has BOTH price-only and a diverging adj_close (a dividend history)
    (hist / "FOO_daily.csv").write_text("date,close\n2026-01-02,100\n2026-01-03,101\n2026-01-04,102\n")
    (tr / "FOO_total_return.csv").write_text(
        "date,close,adj_close\n2026-01-02,100,90\n2026-01-03,101,91\n2026-01-04,102,92\n")
    # BAR: price-only only (no total-return file) -> must fall back
    (hist / "BAR_daily.csv").write_text("date,close\n2026-01-02,50\n2026-01-03,51\n")
    monkeypatch.setattr(MR, "HISTORICAL_DIR", str(hist))
    monkeypatch.setattr(MR, "TR_DIR", str(tr))
    monkeypatch.delenv("GREYLINE_MOMENTUM_TOTAL_RETURN", raising=False)
    return hist, tr


def _closes(eng, sym, hist):
    return [c for _, c in eng._symbol_series(sym, f"{hist}/{sym}_daily.csv")]


def test_flag_off_reads_price_only(dirs):
    hist, _ = dirs
    eng = MR.__new__(MR)                        # avoid __init__ network/env work
    assert MR._total_return_on() is False
    assert _closes(eng, "FOO", hist) == [100.0, 101.0, 102.0]   # price-only close

def test_flag_on_reads_adjusted(dirs, monkeypatch):
    hist, _ = dirs
    monkeypatch.setenv("GREYLINE_MOMENTUM_TOTAL_RETURN", "true")
    eng = MR.__new__(MR)
    assert MR._total_return_on() is True
    assert _closes(eng, "FOO", hist) == [90.0, 91.0, 92.0]      # dividend-adjusted adj_close

def test_flag_on_falls_back_when_tr_missing(dirs, monkeypatch):
    hist, _ = dirs
    monkeypatch.setenv("GREYLINE_MOMENTUM_TOTAL_RETURN", "true")
    eng = MR.__new__(MR)
    # BAR has no total_return file -> must fall back to price-only, never drop the name
    assert _closes(eng, "BAR", hist) == [50.0, 51.0]

def test_universe_source_label_reflects_mode(dirs, monkeypatch):
    eng = MR.__new__(MR)
    # give the fake engine the MIN_BARS gate it needs via a tiny stub signal
    class _Sig:  # noqa
        MIN_BARS = 2
    eng.signal = _Sig()
    _, _, src_off = eng._csv_universe()
    assert src_off == "HISTORICAL_CSV"
    monkeypatch.setenv("GREYLINE_MOMENTUM_TOTAL_RETURN", "true")
    _, _, src_on = eng._csv_universe()
    assert src_on == "TOTAL_RETURN_ADJ"

def test_flag_on_series_is_sorted_oldest_to_newest(dirs, monkeypatch):
    hist, tr = dirs
    monkeypatch.setenv("GREYLINE_MOMENTUM_TOTAL_RETURN", "true")
    # write TR rows out of order — the reader must sort them
    (tr / "FOO_total_return.csv").write_text(
        "date,close,adj_close\n2026-01-04,102,92\n2026-01-02,100,90\n2026-01-03,101,91\n")
    eng = MR.__new__(MR)
    rows = eng._symbol_series("FOO", f"{hist}/FOO_daily.csv")
    assert [d for d, _ in rows] == ["2026-01-02", "2026-01-03", "2026-01-04"]
