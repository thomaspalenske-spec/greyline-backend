"""UW as the second NBBO source for a single option — the safety net under exit pricing. When
TradeStation's option quote is missing/one-sided, UW rescues the exit instead of forcing a
market order (urgent) or a skip (patient)."""

from app.services.uw_option_quote_engine import UWOptionQuoteEngine


def test_parses_tradestation_symbol():
    assert UWOptionQuoteEngine.parse("MRNA 260828C60") == ("MRNA", "260828", "C", 60.0)
    assert UWOptionQuoteEngine.parse("ALAB 260828C315") == ("ALAB", "260828", "C", 315.0)
    assert UWOptionQuoteEngine.parse("SPY 260828P6.5") == ("SPY", "260828", "P", 6.5)
    assert UWOptionQuoteEngine.parse("garbage") is None


def test_builds_occ_symbol_uw_uses():
    # verified live 2026-07-24: MRNA 60C -> MRNA260828C00060000
    assert UWOptionQuoteEngine.occ_symbol("MRNA", "260828", "C", 60.0) == "MRNA260828C00060000"
    assert UWOptionQuoteEngine.occ_symbol("SPY", "260828", "P", 6.5) == "SPY260828P00006500"


def test_expiry_iso():
    assert UWOptionQuoteEngine._expiry_iso("260828") == "2026-08-28"


def test_quote_matches_contract_in_chain(monkeypatch):
    e = UWOptionQuoteEngine()
    chain = {"MRNA260828C00060000": {"nbbo_bid": "3.20", "nbbo_ask": "4.25"}}
    monkeypatch.setattr(e, "_chain", lambda t, x, now: chain)
    assert e.quote("MRNA 260828C60", now=1.0) == (3.20, 4.25)


def test_quote_returns_zeros_when_contract_absent(monkeypatch):
    e = UWOptionQuoteEngine()
    monkeypatch.setattr(e, "_chain", lambda t, x, now: {})
    assert e.quote("MRNA 260828C60", now=1.0) == (0.0, 0.0)


def test_uw_rescues_exit_when_tradestation_quote_is_missing(monkeypatch):
    """The integration point: TS returns nothing usable, UW provides the NBBO, and the exit is a
    priced limit instead of a forced market order."""
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key")
    from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
    import app.services.tradestation_quote_live_engine as tsq
    import app.services.uw_option_quote_engine as uwq

    # TS quote unusable (no two-sided)
    monkeypatch.setattr(tsq.TradeStationQuoteLiveEngine, "get_quote",
                        lambda self, sym: {"response_json": {"Bid": 0, "Ask": 0}})
    # UW has it
    monkeypatch.setattr(uwq.UWOptionQuoteEngine, "quote", lambda self, sym: (3.20, 4.25))

    e = GreyLineSimExecutionEngine()
    bid, ask, source = e._option_quote("MRNA 260828C60")
    assert (bid, ask) == (3.20, 4.25)
    assert source == "unusual_whales"


def test_tradestation_is_preferred_when_it_has_a_quote(monkeypatch):
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key")
    from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
    import app.services.tradestation_quote_live_engine as tsq
    import app.services.uw_option_quote_engine as uwq

    monkeypatch.setattr(tsq.TradeStationQuoteLiveEngine, "get_quote",
                        lambda self, sym: {"response_json": {"Bid": 3.0, "Ask": 3.4}})
    # UW would answer differently; it must NOT be consulted when TS is good
    called = {"uw": False}
    def uw_quote(self, sym):
        called["uw"] = True
        return (9.9, 9.9)
    monkeypatch.setattr(uwq.UWOptionQuoteEngine, "quote", uw_quote)

    e = GreyLineSimExecutionEngine()
    bid, ask, source = e._option_quote("MRNA 260828C60")
    assert (bid, ask, source) == (3.0, 3.4, "tradestation")
    assert called["uw"] is False, "UW budget spent when TradeStation already had the quote"
