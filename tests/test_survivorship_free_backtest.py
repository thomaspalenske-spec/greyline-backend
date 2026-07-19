import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import survivorship_free_backtest as bt


def _write_prices(dirpath, sym, rows):
    dirpath.mkdir(parents=True, exist_ok=True)
    with open(dirpath / f"{sym}_daily.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume", "adj_close"])
        w.writeheader()
        for d, close, vol, adj in rows:
            w.writerow({"date": d, "open": close, "high": close, "low": close,
                        "close": close, "volume": vol, "adj_close": adj})


def test_conviction_matches_the_live_ranking_shape():
    """Live ranks on percentile of |momentum| + percentile of |reversal| so neither leg
    drowns the other. A name strong on both must outrank one strong on a single leg."""
    cands = [
        {"sym": "BOTH", "mom": 50.0, "rev": 9.0},
        {"sym": "MOMONLY", "mom": 900.0, "rev": 0.5},
        {"sym": "WEAK", "mom": 1.0, "rev": 0.4},
    ]
    bt.conviction_ranks(cands)
    ranked = sorted(cands, key=lambda c: c["conviction"], reverse=True)
    assert ranked[0]["sym"] == "BOTH"
    assert ranked[-1]["sym"] == "WEAK"


def test_load_uses_adjusted_close_and_raw_dollar_volume(tmp_path):
    """Returns must come from adj_close (splits/dividends corrupt raw closes), while the
    liquidity gate must use what actually traded: raw close x volume."""
    _write_prices(tmp_path, "AAA", [("2013-01-02", 100.0, 1000, 50.0)])
    (date, adj, dv) = bt.load(tmp_path / "AAA_daily.csv")[0]
    assert (date, adj) == ("2013-01-02", 50.0)
    assert dv == 100.0 * 1000


def _bars(n=310, volume=1_000_000, base=50.0, final_close=None):
    """A series the real signal will actually fire on: 12-month momentum UP with a 5-day
    pullback at the end (mom_bias BULLISH == rev_bias BULLISH). The engine hard-requires
    253 bars, so these fixtures cannot be shortened."""
    from datetime import date, timedelta
    d0 = date(2013, 1, 2)
    rows = []
    for i in range(n):
        if i >= n - 6:
            px = base * 2.0 * (1 - 0.01 * (i - (n - 7)))    # recent pullback
        else:
            px = base * (1 + i / n)                          # steady 12-month rise
        rows.append(((d0 + timedelta(days=i)).isoformat(), round(px, 4), volume, round(px, 4)))
    if final_close is not None:
        d, _, v, _ = rows[-1]
        rows[-1] = (d, final_close, v, final_close)
    return rows


def _run_with(tmp_path, monkeypatch, listings, price_rows, **consts):
    prices = tmp_path / "prices"
    for sym, rows in price_rows.items():
        _write_prices(prices, sym, rows)
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"listings": listings}))

    from app.services.research import point_in_time_universe_engine as pit
    monkeypatch.setattr(bt, "PRICE_DIR", str(prices))
    monkeypatch.setattr(bt, "PointInTimeUniverseEngine",
                        lambda *a, **k: pit.PointInTimeUniverseEngine(snapshot_path=snap))
    for k, v in consts.items():
        monkeypatch.setattr(bt, k, v)


def test_a_delisting_is_exited_at_its_last_price_not_dropped(tmp_path, monkeypatch, capsys):
    """The bias this backtest exists to remove: the original skips any position lacking a
    full horizon of forward bars, which discards a doomed company's final — usually
    catastrophic — period. Here it must be realized."""
    rows = _bars(final_close=2.0)          # liquid, signal fires, then collapses and dies
    listings = [{"ticker": "DEAD", "ipo_date": "2000-01-01",
                 "delisting_date": rows[-1][0], "asset_type": "Stock", "exchange": "NYSE"}]
    _run_with(tmp_path, monkeypatch, listings, {"DEAD": rows}, SPLIT="2013-06-01")
    bt.main()
    out = capsys.readouterr().out
    # the collapse must be counted, not silently skipped
    assert "positions exited at a DELISTING price" in out
    line = [l for l in out.splitlines() if "DELISTING price" in l][0]
    assert not line.rstrip().endswith(" 0"), f"delisting exit was dropped: {line}"


def test_illiquid_and_penny_names_are_excluded(tmp_path, monkeypatch, capsys):
    """A universe of ~10.8k names is mostly microcaps a $10k account cannot fill; measuring
    an edge on them manufactures one."""
    thin = _bars(volume=1)                  # signal fires, but nothing trades
    penny = _bars(volume=10_000_000, base=1.0)   # liquid, but sub-$5
    listings = [{"ticker": t, "ipo_date": "2000-01-01", "delisting_date": "null",
                 "asset_type": "Stock", "exchange": "NYSE"} for t in ("THIN", "PENNY")]
    _run_with(tmp_path, monkeypatch, listings, {"THIN": thin, "PENNY": penny},
              SPLIT="2013-06-01")
    bt.main()
    out = capsys.readouterr().out
    passing = [l for l in out.splitlines() if "passing liquidity+signal" in l][0]
    assert "avg 0" in passing, f"illiquid/penny names leaked through: {passing}"
