"""Per-study survivorship exposure: quantified statement per backtest instead of a blanket caveat.
Index-level studies are clean by construction; single-name studies reaching pre-archive are upper bounds."""

from pathlib import Path

from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine as S


def test_index_level_is_clean_by_construction():
    r = S().study_exposure(["SPY"], index_level=True)
    assert r["index_level"] is True and r["clean"] is True and "construction" in r["note"].lower()


def test_single_name_pre_archive_is_biased_upward(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_read_archive", lambda self: [{"date": "2026-07-23"}])
    reg = tmp_path / "d.json"; reg.write_text('["SIVB", "FRC"]')
    monkeypatch.setattr(S, "DELISTED", reg)
    r = S().study_exposure(["AAPL", "MSFT", "SIVB"], since="2010-01-01")
    assert r["reaches_pre_archive_biased_era"] is True and r["bias_direction"] == "upward"
    assert r["delisted_names_in_universe"] == ["SIVB"] and r["delisted_count_in_universe"] == 1
    assert "UPPER BOUND" in r["note"]


def test_within_archive_window_is_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_read_archive", lambda self: [{"date": "2026-07-23"}])
    reg = tmp_path / "d.json"; reg.write_text('[]')
    monkeypatch.setattr(S, "DELISTED", reg)
    r = S().study_exposure(["EEM", "HYG"], since="2026-08-01")
    assert r["reaches_pre_archive_biased_era"] is False and r["bias_direction"] == "none_observed"


def test_no_archive_treats_as_biased(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_read_archive", lambda self: [])
    monkeypatch.setattr(S, "DELISTED", tmp_path / "none.json")
    r = S().study_exposure(["AAPL"], since="2010-01-01")
    assert "survivorship-biased" in r["note"].lower()
