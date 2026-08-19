"""Data-remediation alert scoping: a CRITICAL bar in a sub-MIN_BARS junk stub (SPAC/warrant/newly-listed)
must NOT page — only criticals in tradeable-history names count. (Paired with the re-scan-after-repair fix
so the alert reflects the POST-repair truth, not stale pre-repair counts.) No network, no orders."""

import app.services.data_remediation_engine as drm
from app.services.data_remediation_engine import DataRemediationEngine as R


def _write(path, bars):
    rows = "\n".join("2026-01-%02d,1,1,1,1,1" % ((i % 28) + 1) for i in range(bars))
    path.write_text("date,open,high,low,close,volume\n" + rows + "\n")


def _bars_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(drm, "BARS_DIR", tmp_path)
    _write(tmp_path / "REAL_daily.csv", 300)     # tradeable (>= MIN_BARS)
    _write(tmp_path / "JUNK_daily.csv", 3)        # junk stub (< MIN_BARS)


def test_tradeable_criticals_excludes_junk(tmp_path, monkeypatch):
    _bars_dir(tmp_path, monkeypatch)
    issues = [{"symbol": "REAL", "type": "NONPOSITIVE"}, {"symbol": "JUNK", "type": "NONPOSITIVE"}]
    out = R._tradeable_criticals(issues)
    assert {i["symbol"] for i in out} == {"REAL"}         # JUNK (3 bars) filtered out


def test_all_junk_criticals_yield_no_alert(tmp_path, monkeypatch):
    _bars_dir(tmp_path, monkeypatch)
    # this is exactly the 2026-08-19 case: residual criticals only in junk stubs (AAAC/ABI) -> no page
    out = R._tradeable_criticals([{"symbol": "JUNK", "type": "NONPOSITIVE"},
                                  {"symbol": "AAAC", "type": "NONPOSITIVE"}])   # AAAC file absent -> 0 bars
    assert out == []


def test_missing_file_treated_as_junk(tmp_path, monkeypatch):
    _bars_dir(tmp_path, monkeypatch)
    out = R._tradeable_criticals([{"symbol": "NOSUCH", "type": "OHLC_VIOLATION"}])
    assert out == []                                      # unreadable/absent -> 0 bars -> not tradeable
