"""The price-bar validator must actually CATCH corruption — including the exact failure
this repo already suffered (one symbol's quote written under every ticker).
"""

import pytest

from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine


HDR = "date,open,high,low,close,volume\n"


def _write(dirpath, symbol, rows):
    p = dirpath / f"{symbol}_daily.csv"
    p.write_text(HDR + "".join(rows))
    return p


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(PriceBarIntegrityEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(PriceBarIntegrityEngine, "OUT", tmp_path / "scan.json")
    return PriceBarIntegrityEngine()


def test_clean_data_passes(eng, tmp_path):
    _write(tmp_path, "AAA", [f"2026-07-{d:02d},10,11,9,10.5,1000\n" for d in range(1, 11)])
    r = eng.scan(full=True, save=False)
    assert r["critical_count"] == 0 and r["ok"] is True


def test_catches_impossible_ohlc(eng, tmp_path):
    # low ABOVE the open — physically impossible (the real MA/TMO/V defect)
    _write(tmp_path, "BBB", ["2026-07-01,10,11,9,10.5,1000\n",
                             "2026-07-02,10.0,11.0,10.5,10.8,1000\n"])
    r = eng.scan(full=True, save=False)
    assert r["ok"] is False
    assert any(i["type"] == "OHLC_VIOLATION" for i in r["issues"])


def test_catches_cross_symbol_duplicate_corruption(eng, tmp_path):
    # THE known corruption: the same close written under many tickers on the same date
    for sym in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        _write(tmp_path, sym, ["2026-07-01,90,99,89,95.1234,1000\n"])
    r = eng.scan(full=True, save=False)
    assert r["ok"] is False
    dup = [i for i in r["issues"] if i["type"] == "DUPLICATE_CROSS_SYMBOL"]
    assert dup and "5 symbols" in dup[0]["detail"]


def test_catches_nonpositive_price(eng, tmp_path):
    _write(tmp_path, "CCC", ["2026-07-01,0,0,0,0,0\n"])
    r = eng.scan(full=True, save=False)
    assert r["ok"] is False
    assert any(i["type"] == "NONPOSITIVE" for i in r["issues"])


def test_flags_frozen_series_as_warning_not_critical(eng, tmp_path):
    _write(tmp_path, "DDD", [f"2026-07-{d:02d},10,11,9,10.0,1000\n" for d in range(1, 12)])
    r = eng.scan(full=True, save=False)
    assert any(i["type"] == "FROZEN_SERIES" for i in r["issues"])
    assert r["critical_count"] == 0          # unusual, but not corrupt

def test_scan_if_due_gates_to_once_per_interval(eng, tmp_path):
    """The scheduler calls this every cycle — it must NOT rescan 3.4M rows each time."""
    _write(tmp_path, "AAA", ["2026-07-01,10,11,9,10.5,1000\n"])
    first = eng.scan_if_due(hours=24)
    assert first["ran"] is True                      # nothing saved yet -> runs
    second = eng.scan_if_due(hours=24)
    assert second["ran"] is False                    # fresh scan exists -> skipped
    assert second["status"] == "PRICE_BAR_SCAN_NOT_DUE"
    third = eng.scan_if_due(hours=0)                 # interval elapsed -> runs again
    assert third["ran"] is True


def test_large_move_does_not_claim_split(eng, tmp_path):
    # a real crash (-60%) must NOT be asserted to be a split
    _write(tmp_path, "EEE", ["2026-07-01,100,101,99,100,1000\n",
                             "2026-07-02,40,41,39,40,1000\n"])
    r = eng.scan(full=True, save=False)
    mv = [i for i in r["issues"] if i["type"] == "LARGE_MOVE"]
    assert mv and "likely a real event" in mv[0]["detail"]
    assert r["critical_count"] == 0


# --- cross-source reconciliation: the CSVs vs an INDEPENDENT source -------------------

def _cross(monkeypatch, tmp_path, csv_rows, live_bars):
    """Wire the cross-source engine to a temp CSV and a faked TradeStation barchart."""
    from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
    from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine

    monkeypatch.setattr(PriceBarCrossSourceEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(PriceBarCrossSourceEngine, "OUT", tmp_path / "out.json")
    monkeypatch.setattr(PriceBarCrossSourceEngine, "STATE", tmp_path / "cursor.json")
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    (tmp_path / "XYZ_daily.csv").write_text(HDR + "".join(csv_rows))
    monkeypatch.setattr(MomentumReversalStrategyEngine, "_fetch_daily_closes",
                        lambda self, sym, base, tok: list(live_bars))
    return PriceBarCrossSourceEngine()


def test_cross_source_passes_when_bars_agree(tmp_path, monkeypatch):
    rows = [f"2026-06-{d:02d},10,11,9,{100 + d}.0,1000\n" for d in range(1, 11)]
    live = [(f"2026-06-{d:02d}", 100.0 + d) for d in range(1, 11)]
    eng = _cross(monkeypatch, tmp_path, rows, live)
    r = eng.reconcile(symbols=["XYZ"], save=False)
    assert r["ok"] is True and r["mismatched"] == 0
    assert r["results"][0]["verdict"] == "MATCH"


def test_cross_source_catches_an_unadjusted_split(tmp_path, monkeypatch):
    """THE failure self-consistency cannot see: our CSV never applied a 2:1 split, so every
    bar is exactly 2x the adjusted truth — internally perfect, completely wrong. ATR and
    every doctrine stop computed off it would be double-sized."""
    rows = [f"2026-06-{d:02d},10,11,9,{(100 + d) * 2}.0,1000\n" for d in range(1, 11)]
    live = [(f"2026-06-{d:02d}", 100.0 + d) for d in range(1, 11)]
    eng = _cross(monkeypatch, tmp_path, rows, live)
    r = eng.reconcile(symbols=["XYZ"], save=False)
    assert r["ok"] is False and r["mismatched"] == 1
    m = r["mismatches"][0]
    assert m["verdict"] == "UNADJUSTED_SPLIT_SUSPECTED"
    assert abs(m["median_ratio"] - 2.0) < 0.02


def test_cross_source_tolerates_float_rounding(tmp_path, monkeypatch):
    """Real data differs in the 4th decimal (258.859985 vs 258.86). That must NOT alarm."""
    rows = [f"2026-06-{d:02d},10,11,9,{100 + d}.009985,1000\n" for d in range(1, 11)]
    live = [(f"2026-06-{d:02d}", 100.01 + d) for d in range(1, 11)]
    eng = _cross(monkeypatch, tmp_path, rows, live)
    r = eng.reconcile(symbols=["XYZ"], save=False)
    assert r["ok"] is True


def test_cross_source_rotates_coverage(tmp_path, monkeypatch):
    """Rate limits forbid scanning 557 symbols daily, so the cursor must advance and
    eventually cover everything rather than re-checking the same head every run."""
    from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine
    monkeypatch.setattr(PriceBarCrossSourceEngine, "STATE", tmp_path / "cursor.json")
    eng = PriceBarCrossSourceEngine()
    universe = [f"S{i:03d}" for i in range(10)]
    first, _ = eng._next_batch(universe, 4)
    second, _ = eng._next_batch(universe, 4)
    assert first == universe[0:4]
    assert second == universe[4:8]
    assert set(first) & set(second) == set()


# --- tradability: were these bars actually TRADED? -----------------------------------

def _trad(monkeypatch, tmp_path):
    from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
    monkeypatch.setattr(PriceBarTradabilityEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(PriceBarTradabilityEngine, "OUT", tmp_path / "trad.json")
    return PriceBarTradabilityEngine()


def _bars(n, close, vol, start_day=1):
    # dates don't need to be real trading days for this engine — only order matters
    return [f"2020-01-01,{close},{close},{close},{close},{vol}\n"] * 0 or [
        f"{2000 + (start_day + i)//300}-01-{(i % 28) + 1:02d},{close},{close},{close},{close},{vol}\n"
        for i in range(n)]


def test_tradability_flags_a_pre_listing_stub(tmp_path, monkeypatch):
    """Smurfit Westrock's real shape: years of ~$180/day prints, then a real US listing."""
    eng = _trad(monkeypatch, tmp_path)
    rows = _bars(300, 30.0, 6) + _bars(300, 30.0, 500_000)   # $180/day then $15M/day
    (tmp_path / "SW_daily.csv").write_text(HDR + "".join(rows))
    r = eng.analyze_symbol("SW")
    assert r["untradable_prefix_bars"] == 300
    assert r["untradable_prefix_pct"] == 50.0
    assert r["stub_inside_signal_window"] is False      # 300 clean bars > 253 needed


def test_tradability_catches_a_stub_inside_the_signal_window(tmp_path, monkeypatch):
    """THE live hazard: 253 RAW bars are available, but almost none were traded."""
    eng = _trad(monkeypatch, tmp_path)
    rows = _bars(280, 30.0, 6) + _bars(30, 30.0, 500_000)   # only 30 real bars at the end
    (tmp_path / "STUB_daily.csv").write_text(HDR + "".join(rows))
    r = eng.analyze_symbol("STUB")
    assert r["stub_inside_signal_window"] is True
    assert r["usable_signal_bars"] == 30                # not the 253 MIN_BARS implies


def test_tradability_does_not_punish_a_small_but_traded_symbol(tmp_path, monkeypatch):
    """A relative-to-recent-volume test flagged XLE/XLP as 18% untradable because they GREW.
    Dollar volume against a fixed floor must call a genuinely-traded small name tradable."""
    eng = _trad(monkeypatch, tmp_path)
    rows = _bars(100, 25.0, 100_000) + _bars(300, 90.0, 5_000_000)   # $2.5M/day -> $450M/day
    (tmp_path / "XLE_daily.csv").write_text(HDR + "".join(rows))
    r = eng.analyze_symbol("XLE")
    assert r["untradable_prefix_bars"] == 0
    assert r["stub_inside_signal_window"] is False


def test_universe_exclusion_fails_open_without_a_scan(tmp_path, monkeypatch):
    """A missing data-quality file must never empty the universe and halt trading."""
    from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
    monkeypatch.setattr(PriceBarTradabilityEngine, "OUT", tmp_path / "absent.json")
    assert PriceBarTradabilityEngine().contaminated_symbols() == set()
