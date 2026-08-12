"""Extended ETF universe: the 52 scanned ETFs registered as TRACKED candidates (not armed). The quote stream
live-tracks the non-caution names; the 2x leveraged/single-stock products are registered but never offered
to a sleeve."""

from app.services.extended_etf_universe_engine import ExtendedEtfUniverseEngine as E
from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine as S

CAUTION = {"BITX", "MSTU", "MUU", "MULL"}


def test_registry_is_52_clean_tickers():
    u = E.UNIVERSE
    assert len(u) == 52
    assert all(t == t.upper() and t.isascii() for t in u)          # clean uppercase tickers
    assert len(set(u)) == 52                                        # no dups


def test_caution_products_excluded_from_tradeable():
    tradeable = set(E.symbols(include_caution=False))
    assert CAUTION.isdisjoint(tradeable)                           # 2x leveraged never tradeable
    assert len(tradeable) == 48
    assert set(E.symbols(include_caution=True)) - tradeable == CAUTION


def test_for_sleeve_maps_and_never_returns_caution():
    mom = E.for_sleeve("momentum")
    assert "MTUM" in mom and "SPMO" in mom
    assert CAUTION.isdisjoint(set(mom))
    mf = E.for_sleeve("managed_futures")
    assert {"IEI", "EMB", "INDA"} <= set(mf)
    assert E.for_sleeve("trend")                                   # non-empty


def test_snapshot_counts():
    s = E.snapshot()
    assert s["count"] == 52 and s["tradeable_count"] == 48 and s["caution_count"] == 4
    assert "by_subclass" in s and s["status"] == "EXTENDED_ETF_UNIVERSE"


def test_stream_tracks_extended_universe_but_not_caution(monkeypatch):
    monkeypatch.delenv("GREYLINE_TS_STREAM_SYMBOLS", raising=False)
    monkeypatch.delenv("GREYLINE_TS_STREAM_MAX", raising=False)
    syms = set(S._symbols())
    assert {"MTUM", "IEI", "INDA", "GDXJ"} <= syms                 # extended names tracked
    assert "SPY" in syms                                           # core still there
    assert CAUTION.isdisjoint(syms)                                # leveraged NOT streamed
    assert len(S._symbols()) <= 96                                 # capped


def test_momentum_factor_excludes_the_extended_etfs():
    # the ETF bars live in the same directory as the single-stock universe (so ETF sleeves can read them),
    # but the momentum-reversal FACTOR must exclude them — diversified funds would muddy a single-stock signal
    from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine as M
    excluded = M()._excluded_symbols()
    assert set(E.symbols(include_caution=True)) <= excluded
