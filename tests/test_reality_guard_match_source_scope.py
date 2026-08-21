"""MATCH_SOURCE cry-wolf fix: a cross-source VALUE mismatch pages ONLY for a tradeable, in-universe, unresolved
symbol — not a thin sub-253-bar penny stub (CAST), an untraded name, or a file restated since the scan."""

from datetime import datetime, timedelta

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as RG


def _csv(path, nbars):
    path.write_text("date,open,high,low,close,volume\n" +
                    "".join(f"2020-01-{i%28+1:02d},1,1,1,1,1\n" for i in range(nbars)))


def test_thin_stub_does_not_page(tmp_path):
    _csv(tmp_path / "CAST_daily.csv", 114)                       # penny stub, < 253 bars
    scan = datetime(2026, 8, 21, 0, 0, 0)
    live_bad, restated, thin, inert = RG._scope_source_mismatches(
        [{"symbol": "CAST"}], active=None, run_ts=scan, bars_dir=tmp_path)
    assert live_bad == [] and thin == ["CAST"]                  # filtered as thin — no page


def test_tradeable_unresolved_symbol_pages(tmp_path):
    f = tmp_path / "ABC_daily.csv"
    _csv(f, 300)                                                 # tradeable, >= 253 bars
    import os
    old = (datetime(2026, 8, 21) + timedelta(days=1)).timestamp()  # mtime BEFORE the (later) scan
    os.utime(f, (old, old))
    scan = datetime(2026, 8, 25)                                 # scan is AFTER the file mtime -> not restated
    live_bad, restated, thin, inert = RG._scope_source_mismatches(
        [{"symbol": "ABC"}], active=None, run_ts=scan, bars_dir=tmp_path)
    assert live_bad == ["ABC"]                                   # real, unresolved -> pages


def test_restated_since_scan_does_not_page(tmp_path):
    f = tmp_path / "ABC_daily.csv"
    _csv(f, 300)                                                 # tradeable, but rewritten AFTER the scan
    import os
    new = (datetime(2026, 8, 25) + timedelta(days=1)).timestamp()
    os.utime(f, (new, new))
    scan = datetime(2026, 8, 25)
    live_bad, restated, thin, inert = RG._scope_source_mismatches(
        [{"symbol": "ABC"}], active=None, run_ts=scan, bars_dir=tmp_path)
    assert live_bad == [] and restated == ["ABC"]               # likely self-healed -> re-verify, no page


def test_out_of_universe_is_inert(tmp_path):
    _csv(tmp_path / "ABC_daily.csv", 300)
    live_bad, restated, thin, inert = RG._scope_source_mismatches(
        [{"symbol": "ABC"}], active={"SPY", "QQQ"}, run_ts=None, bars_dir=tmp_path)
    assert live_bad == [] and inert == ["ABC"]                  # not in the active universe -> inert


def test_scope_tradeable_symbols_partitions_clean_and_source(tmp_path):
    """The shared tradeable-scope (used by BOTH PRICE_BARS_CLEAN and MATCH_SOURCE): only tradeable, in-universe
    names are in_scope; thin sub-253-bar stubs (the AAAC/ABI corrupt-bar case) and missing files are inert-thin."""
    _csv(tmp_path / "BIG_daily.csv", 300)                        # tradeable
    _csv(tmp_path / "THIN_daily.csv", 100)                       # sub-253 stub
    in_scope, thin, inert = RG._scope_tradeable_symbols(["BIG", "THIN", "GONE"], active=None, bars_dir=tmp_path)
    assert in_scope == ["BIG"]                                   # only the tradeable name alarms
    assert set(thin) == {"THIN", "GONE"}                         # stub + missing-file both filtered


def test_scope_tradeable_respects_active_universe(tmp_path):
    _csv(tmp_path / "BIG_daily.csv", 300)                        # tradeable but out of the active universe
    in_scope, thin, inert = RG._scope_tradeable_symbols(["BIG"], active={"SPY"}, bars_dir=tmp_path)
    assert in_scope == [] and inert == ["BIG"]
