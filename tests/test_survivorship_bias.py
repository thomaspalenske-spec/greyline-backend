"""Survivorship-bias quantification must be HONEST: measure the disappearance rate, exclude
the batch-flag artifact, and never overstate a raw rate as the return bias."""

import json

import pytest

from app.services.survivorship_bias_engine import SurvivorshipBiasEngine


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(SurvivorshipBiasEngine, "LISTINGS", tmp_path / "listings.json")
    monkeypatch.setattr(SurvivorshipBiasEngine, "HIST_DIR", tmp_path / "hist")
    monkeypatch.setattr(SurvivorshipBiasEngine, "OUT", tmp_path / "out.json")
    (tmp_path / "hist").mkdir()
    return SurvivorshipBiasEngine, tmp_path


def _listings(tmp_path, rows, fetched="2026-07-19"):
    (tmp_path / "listings.json").write_text(json.dumps({"fetched_at": fetched, "listings": rows}))


def _stock(ticker, ipo, delisted=None):
    return {"ticker": ticker, "name": ticker + " Inc", "asset_type": "Stock",
            "exchange": "NYSE", "ipo_date": ipo, "delisting_date": delisted or "null"}


def test_measures_disappearance_rate(eng):
    Eng, tmp = eng
    rows = [_stock("SURV", "2005-01-01")]                       # survivor
    rows += [_stock(f"D{i}", "2005-01-01", "2018-06-01") for i in range(3)]   # 3 delisted mid-window
    _listings(tmp, rows)
    m = Eng().measure("2015-01-01", "2026-01-01")
    assert m["listed_at_start"] == 4
    assert m["disappeared"] == 3
    assert m["disappearance_rate_pct"] == 75.0


def test_batch_flag_artifact_is_excluded(eng):
    """368 tickers stamped 2 days before the snapshot are a batch artifact, not real
    delistings. A delisting inside the artifact lag must NOT count."""
    Eng, tmp = eng
    rows = [_stock("SURV", "2005-01-01")]
    rows += [_stock(f"A{i}", "2005-01-01", "2026-07-17") for i in range(50)]   # artifact zone
    _listings(tmp, rows, fetched="2026-07-19")
    m = Eng().measure("2015-01-01", "2026-07-19")
    assert m["disappeared"] == 0                                # all inside the artifact lag


def test_report_states_it_is_an_upper_bound_not_the_return_bias(eng):
    """The engine must never present the raw rate as the return overstatement — acquisitions
    are captured, not missed, and reasons aren't in the feed."""
    Eng, tmp = eng
    _listings(tmp, [_stock("SURV", "2005-01-01"), _stock("D", "2005-01-01", "2018-01-01")])
    r = Eng().assess()
    interp = r["interpretation"]
    assert "bound" in interp["is_an_upper_bound"].lower()  # "bounds names missing, not return"
    assert "not the return" in interp["is_an_upper_bound"].lower()
    assert "reason" in interp["cannot_measure"].lower()
    assert "vendor" in interp["unfixable_for_free"].lower()


def test_no_snapshot_degrades_cleanly(eng):
    Eng, tmp = eng   # no listings file written
    r = Eng().assess()
    assert r["status"] == "NO_LISTINGS_SNAPSHOT" and r["ok"] is None


def test_warrants_and_units_are_not_counted_as_stock_delistings(eng):
    Eng, tmp = eng
    rows = [_stock("REAL", "2005-01-01", "2018-01-01"),
            {"ticker": "SPAC-WS", "name": "warrant", "asset_type": "Stock",
             "exchange": "NYSE", "ipo_date": "2005-01-01", "delisting_date": "2018-01-01"},
            {"ticker": "SPAC-U", "name": "unit", "asset_type": "Stock",
             "exchange": "NYSE", "ipo_date": "2005-01-01", "delisting_date": "2018-01-01"}]
    _listings(tmp, rows)
    m = Eng().measure("2015-01-01", "2026-01-01")
    assert m["disappeared"] == 1                                # only REAL, not the warrant/unit
