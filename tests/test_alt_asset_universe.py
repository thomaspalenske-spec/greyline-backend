"""Alt-asset universe: the 3 previously-untouched classes (vol ETPs, futures, spot FX) registered as tracked
candidates with backfilled bars. vol ETPs tradeable via equity execution (streamed, momentum-excluded);
futures + FX need their own plumbing (separate bar store, tradeable_now=False)."""

from app.services.alt_asset_universe_engine import AltAssetUniverseEngine as A
from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine as S


def test_registry_classes_and_counts():
    by = A.by_class()
    assert set(by) == {"vol_etp", "futures", "fx"}
    assert len(by["vol_etp"]) == 5 and len(by["fx"]) == 6 and len(by["futures"]) == 19
    assert A.snapshot()["count"] == 30


def test_only_vol_etps_are_tradeable_now():
    tradeable = set(A.symbols(tradeable_only=True))
    assert tradeable == {"VXX", "VIXY", "UVXY", "UVIX", "SVIX"}     # only the equity ETPs
    # futures + FX explicitly need plumbing
    assert set(A.snapshot()["needs_plumbing"]) == set(A.symbols(asset_class="futures")) | set(A.symbols(asset_class="fx"))


def test_bar_store_routes_by_class():
    # vol ETPs live in the equity store; futures/FX in the separate alt store (never the equity universe)
    assert str(A.bar_path("VXX")).endswith("historical/VXX_daily.csv")
    assert "alt_assets" in str(A.bar_path("ES")) and str(A.bar_path("ES")).endswith("ES_daily.csv")
    assert "alt_assets" in str(A.bar_path("EURUSD"))


def test_caution_flags_the_leveraged_vol():
    caution = {i["key"] for i in A.all() if i["caution"]}
    assert caution == {"UVXY", "UVIX", "SVIX"}                      # 1.5x/2x/-1x decay products
    assert set(A.vol_etp_symbols(include_caution=False)) == {"VXX", "VIXY"}


def test_momentum_factor_excludes_vol_etps():
    from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine as M
    excluded = M()._excluded_symbols()
    assert set(A.vol_etp_symbols()) <= excluded                    # ETPs kept out of the single-stock factor


def test_stream_tracks_clean_vol_etps_not_leveraged(monkeypatch):
    monkeypatch.delenv("GREYLINE_TS_STREAM_SYMBOLS", raising=False)
    monkeypatch.delenv("GREYLINE_TS_STREAM_MAX", raising=False)
    syms = set(S._symbols())
    assert {"VXX", "VIXY"} <= syms                                  # clean long-vol tracked
    assert {"UVIX", "SVIX"}.isdisjoint(syms)                        # leveraged/inverse NOT streamed
