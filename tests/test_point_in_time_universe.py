import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research.point_in_time_universe_engine import PointInTimeUniverseEngine


def _engine(tmp_path, listings):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"listings": listings}))
    return PointInTimeUniverseEngine(snapshot_path=p)


def _row(ticker, ipo, delisted="null", asset_type="Stock", exchange="NYSE"):
    return {"ticker": ticker, "ipo_date": ipo, "delisting_date": delisted,
            "asset_type": asset_type, "exchange": exchange}


def test_includes_a_company_while_it_traded_and_drops_it_after(tmp_path):
    """The whole point: a name that later died must be IN the universe for the dates it
    was alive. AMR Corp traded through 2013-12-17 and then merged away."""
    e = _engine(tmp_path, [_row("AAMRQ", "2001-01-02", "2013-12-17")])
    assert e.resolve("2013-06-28") == ["AAMRQ"]
    assert e.resolve("2013-12-16") == ["AAMRQ"]
    assert e.resolve("2014-06-30") == []


def test_excludes_a_company_before_its_ipo(tmp_path):
    e = _engine(tmp_path, [_row("ABNB", "2020-12-10")])
    assert e.resolve("2019-06-30") == []
    assert e.resolve("2021-06-30") == ["ABNB"]


def test_bankrupt_tickers_are_kept_but_derivatives_are_not(tmp_path):
    """Q means in-bankruptcy common stock and MUST survive the filter — dropping it would
    re-introduce the survivorship bias. Warrants, units, preferreds and bonds must not."""
    e = _engine(tmp_path, [
        _row("AAMRQ", "2001-01-02"),        # bankrupt common — keep
        _row("BRK-B", "1996-05-09"),        # dual-class common — keep
        _row("ABEOW", "2015-01-01"),        # 5th-letter warrant — drop
        _row("ACAMU", "2015-01-01"),        # unit — drop
        _row("ABR-P-A", "2015-01-01"),      # preferred — drop
        _row("ACEL-WS", "2015-01-01"),      # warrant — drop
        _row("ASRV 8.45 06-30-28", "2015-01-01"),   # bond — drop
    ])
    assert e.resolve("2016-06-30") == ["AAMRQ", "BRK-B"]


def test_common_only_can_be_disabled(tmp_path):
    e = _engine(tmp_path, [_row("ABEOW", "2015-01-01")])
    assert e.resolve("2016-06-30") == []
    assert e.resolve("2016-06-30", common_only=False) == ["ABEOW"]


def test_refuses_dates_where_coverage_is_not_survivorship_free(tmp_path):
    """UW has almost no delistings before 2013, so an earlier universe would silently omit
    the failures. Refuse rather than return a flattering answer."""
    e = _engine(tmp_path, [_row("AAPL", "1980-12-12")])
    with pytest.raises(ValueError, match="survivorship-free"):
        e.resolve("2008-09-15")


def test_survivorship_check_reports_the_dead(tmp_path):
    e = _engine(tmp_path, [
        _row("AAPL", "1980-12-12"),
        _row("AAMRQ", "2001-01-02", "2013-12-17"),
    ])
    out = e.survivorship_check("2013-06-28")
    assert out["universe"] == 2
    assert out["since_delisted"] == 1
    assert out["examples"] == ["AAMRQ"]
