"""Execution-cost profile: correct round-trip-spread math and the cost flags (cheap / costly / non-viable)."""

from app.services.execution_cost_engine import ExecutionCostEngine as X


def test_round_trip_bps_math():
    e = X()
    # bid 99.90 / ask 100.10 -> spread 0.20 on mid 100 = 20 bps
    assert e._round_trip_bps(99.90, 100.10) == 20.0
    assert e._round_trip_bps(0, 100) is None            # no bid
    assert e._round_trip_bps(None, None) is None


class FakeQuotes:
    def __init__(self, spreads):
        self.s = spreads                                # {sym: (bid, ask)}

    def get_quote(self, sym):
        bid, ask = self.s.get(sym, (0, 0))
        return {"response_json": {"Quotes": [{"Bid": bid, "Ask": ask}]}}


def _patch(monkeypatch, spreads):
    monkeypatch.setattr(X, "FIXED", {"carry": ["SVXY"], "trend": ["QQQM"], "tbill": ["SGOV"]})
    monkeypatch.setattr(X, "_held_by_sleeve", lambda self: {"premium": [], "momentum": []})
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: FakeQuotes(spreads))


def test_cheap_liquid_etf_flagged_cheap(monkeypatch):
    _patch(monkeypatch, {"SVXY": (57.0, 57.02), "QQQM": (279.9, 280.0), "SGOV": (100.49, 100.50)})
    out = X().profile()["sleeves"]
    assert out["carry"]["flag"] == "cheap" and out["trend"]["flag"] == "cheap"


def test_wide_spread_flagged_nonviable(monkeypatch):
    # a 2%-wide option-like spread -> ~200 bps round trip -> non-viable
    _patch(monkeypatch, {"SVXY": (1.00, 1.02), "QQQM": (279.9, 280.0), "SGOV": (100.49, 100.50)})
    out = X().profile()["sleeves"]
    assert out["carry"]["worst_round_trip_bps"] > 100 and "NON-VIABLE" in out["carry"]["flag"]
