"""Total-return adjustment must be economically correct — the errors here are silent and
systematic, so each property is pinned against a hand-computable case."""

import csv

import pytest

from app.services.total_return_series_engine import TotalReturnSeriesEngine

HDR = "date,open,high,low,close,volume\n"


class FakeProvider:
    """Serve fixed dividend/split payloads so the math is tested without the network."""
    def __init__(self, dividends=None, splits=None):
        self._div = dividends or []
        self._spl = splits or []

    def _get(self, path, params=None, **k):
        if path.endswith("/dividends"):
            return {"data": {"dividends": self._div}}
        if path.endswith("/splits"):
            return {"data": {"splits": self._spl}}
        return {"data": {}}


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(TotalReturnSeriesEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(TotalReturnSeriesEngine, "OUT_DIR", tmp_path / "tr")
    monkeypatch.setattr(TotalReturnSeriesEngine, "REPORT", tmp_path / "rep.json")
    return TotalReturnSeriesEngine


def _days(const_close=None, start=100):
    """40 trading bars across two months so the engine's 30-bar minimum is satisfied."""
    out = []
    for m, dmax in ((5, 20), (6, 20)):
        for d in range(1, dmax + 1):
            c = const_close if const_close is not None else start + (len(out))
            out.append(f"2026-{m:02d}-{d:02d},10,10,10,{c},1000000\n")
    return out


def _write(tmp_path, sym, rows):
    (tmp_path / f"{sym}_daily.csv").write_text(HDR + "".join(rows))


def _adj(tmp_path, sym):
    return [(r["date"], float(r["close"]), float(r["adj_close"]))
            for r in csv.DictReader(open(tmp_path / "tr" / f"{sym}_total_return.csv"))]


def test_todays_adjusted_close_equals_the_real_close(eng, tmp_path):
    """The series is back-adjusted, so the most recent bar must be unadjusted — otherwise
    'current price' silently disagrees with the broker."""
    _write(tmp_path, "AAA", _days())
    e = eng(provider=FakeProvider(dividends=[{"ex_date": "2026-06-10", "amount": 2.0}]))
    e.build_symbol("AAA")
    rows = _adj(tmp_path, "AAA")
    assert abs(rows[-1][1] - rows[-1][2]) < 1e-6


def test_a_dividend_scales_history_down_never_up(eng, tmp_path):
    """Reinvested dividends make PAST prices lower relative to today. adj_close must never
    exceed the raw close anywhere in history."""
    _write(tmp_path, "AAA", _days(const_close=100))
    e = eng(provider=FakeProvider(dividends=[{"ex_date": "2026-06-10", "amount": 5.0}]))
    e.build_symbol("AAA")
    rows = _adj(tmp_path, "AAA")
    assert all(a <= c + 1e-9 for _, c, a in rows)
    assert any(a < c - 1e-9 for _, c, a in rows[:5])   # pre-dividend bars actually adjusted


def test_dividend_is_split_adjusted_to_the_price_basis(eng, tmp_path):
    """THE trap: UW amounts are raw (pre-split), our prices are split-adjusted. A $2 dividend
    paid before a 2:1 split is worth $1 in today's share basis. Applying the raw $2 would
    double the adjustment. Two files, identical prices, identical dividend — one with a later
    split — must produce the SAME adjusted history."""
    prices = _days(const_close=100)
    _write(tmp_path, "NOSPLIT", prices)
    _write(tmp_path, "SPLIT", prices)
    div = [{"ex_date": "2026-06-05", "amount": 2.0}]      # raw $2 before...
    eng(provider=FakeProvider(dividends=div)).build_symbol("NOSPLIT")
    # ...a 2:1 split AFTER the dividend: raw $2 should be halved to $1 on the price basis
    eng(provider=FakeProvider(dividends=div,
                              splits=[{"effective_date": "2026-06-12", "split_factor": 2.0}])
        ).build_symbol("SPLIT")
    no = _adj(tmp_path, "NOSPLIT")
    sp = _adj(tmp_path, "SPLIT")
    # NOSPLIT applied the full $2; SPLIT applied $1, so SPLIT's history is adjusted LESS
    assert sp[0][2] > no[0][2] + 1e-6, "split-adjustment of the dividend was not applied"


def test_a_non_paying_stock_is_unchanged(eng, tmp_path):
    """No dividends -> adj_close must equal close everywhere. Guards against an adjustment
    that quietly inflates growth names (NVDA/AAPL) which barely pay."""
    _write(tmp_path, "GROW", _days())
    eng(provider=FakeProvider()).build_symbol("GROW")
    assert all(abs(c - a) < 1e-9 for _, c, a in _adj(tmp_path, "GROW"))


def test_a_spinoff_distribution_is_excluded_not_treated_as_cash(eng, tmp_path):
    """UW's dividend feed lists SPINOFFS as huge 'dividends' (JCI: $88 on a $28 stock, 319%).
    Treating one as reinvestable cash drove the factor to ~0 and collapsed the whole history,
    faking a +177%/yr total return. Anything above a sane fraction of price must be excluded
    and flagged, leaving the adjusted history close to price-only."""
    # flat $100 stock, one absurd "dividend" of $60 (60% of price) mid-series
    rows = _days(const_close=100)
    _write(tmp_path, "SPIN", rows)
    e = eng(provider=FakeProvider(dividends=[{"ex_date": "2026-06-05", "amount": 60.0}]))
    r = e.build_symbol("SPIN")
    assert r["special_distributions_excluded"] == 1
    assert r["dividends_applied"] == 0                      # nothing legitimate to reinvest
    adj = _adj(tmp_path, "SPIN")
    # history must NOT be collapsed — adj stays ~equal to the flat $100 price
    assert all(abs(a - 100.0) < 1e-6 for _, _, a in adj)


def test_a_large_but_legitimate_special_dividend_is_still_applied(eng, tmp_path):
    """A ~10% special cash dividend (MSFT 2004) is real and reinvestable — it must NOT be
    swept out with the spinoffs. Only clearly-non-cash distributions (>25%) are excluded."""
    _write(tmp_path, "SPEC", _days(const_close=100))
    e = eng(provider=FakeProvider(dividends=[{"ex_date": "2026-06-05", "amount": 10.0}]))  # 10%
    r = e.build_symbol("SPEC")
    assert r["special_distributions_excluded"] == 0
    assert r["dividends_applied"] == 1
    adj = _adj(tmp_path, "SPEC")
    assert any(a < c - 1e-6 for _, c, a in adj[:3])         # pre-dividend history adjusted
