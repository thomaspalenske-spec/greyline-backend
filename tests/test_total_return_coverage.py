"""Total-return coverage metric + incremental self-maintenance. Deterministic tmp fixtures; build_symbol
is stubbed so no UW calls. No network, no orders."""

import pytest

from app.services.total_return_series_engine import TotalReturnSeriesEngine as T


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    hist = tmp_path / "hist"; out = tmp_path / "out"
    hist.mkdir(); out.mkdir()
    monkeypatch.setattr(T, "HIST_DIR", hist)
    monkeypatch.setattr(T, "OUT_DIR", out)
    monkeypatch.setattr(T, "_min_bars", staticmethod(lambda: 3))
    three = "date,close\n2026-01-01,10\n2026-01-02,11\n2026-01-03,12\n"
    for s in ("BIG1", "BIG2", "BIG3"):
        (hist / f"{s}_daily.csv").write_text(three)          # 3 bars -> eligible
    (hist / "SMALL_daily.csv").write_text("date,close\n2026-01-01,10\n")   # 1 bar -> junk, excluded
    (out / "BIG1_total_return.csv").write_text("date,close,adj_close\n2026-01-01,10,9\n")  # only BIG1 covered
    return hist, out


def test_coverage_excludes_junk_and_counts_eligible(dirs):
    c = T().coverage()
    assert c["eligible"] == 3                    # BIG1/2/3 ; SMALL (<3 bars) excluded
    assert c["covered"] == 1                     # BIG1
    assert c["uncovered"] == 2                   # BIG2, BIG3
    assert c["coverage_pct"] == 33.3
    assert c["healthy"] is False                 # below the 90% guard threshold
    assert set(c["uncovered_sample"]) == {"BIG2", "BIG3"}


def test_coverage_healthy_when_full(dirs):
    _, out = dirs
    for s in ("BIG2", "BIG3"):
        (out / f"{s}_total_return.csv").write_text("date,close,adj_close\n2026-01-01,10,9\n")
    c = T().coverage()
    assert c["uncovered"] == 0 and c["coverage_pct"] == 100.0 and c["healthy"] is True


def test_uncovered_eligible_sorted(dirs):
    unc, elig = T()._uncovered_eligible()
    assert unc == ["BIG2", "BIG3"] and elig == 3


def test_build_missing_caps_and_targets_uncovered(dirs, monkeypatch):
    calls = []
    monkeypatch.setattr(T, "build_symbol",
                        lambda self, s, save=True: calls.append(s) or {"status": "TOTAL_RETURN_BUILT"})
    r = T().build_missing(limit=1)
    assert r["attempted"] == 1 and r["built"] == 1
    assert calls == ["BIG2"]                      # sorted-first uncovered eligible, capped at limit

def test_build_missing_counts_failures(dirs, monkeypatch):
    monkeypatch.setattr(T, "build_symbol",
                        lambda self, s, save=True: {"status": "TOTAL_RETURN_NO_BARS"})
    r = T().build_missing(limit=5)
    assert r["attempted"] == 2 and r["built"] == 0 and r["failed"] == 2
