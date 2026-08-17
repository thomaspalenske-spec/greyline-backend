"""Selection must reject a contract that is cheap to BUY but expensive to TRADE, and prefer the
cheaper-to-trade one — the exact failure that put the 28%-wide contract in the book."""


def test_affordable_contract_rejects_wide_prefers_tight(monkeypatch):
    from app.services.momentum_options_execution_engine import MomentumOptionsExecutionEngine

    eng = MomentumOptionsExecutionEngine()

    # Two affordable calls: one tight (good to trade), one very wide (the disaster). Both fit a
    # $1,000 budget; the old sort would take the wide one if it had more open interest.
    chain = {"contracts": [
        {"Side": "Call", "Bid": 3.20, "Ask": 4.25, "Mid": 3.72, "Delta": 0.42,
         "DailyOpenInterest": 5000, "Strike": 60, "Legs": [{"Symbol": "WIDE 260828C60"}]},
        {"Side": "Call", "Bid": 5.90, "Ask": 6.10, "Mid": 6.00, "Delta": 0.55,
         "DailyOpenInterest": 800, "Strike": 55, "Legs": [{"Symbol": "TIGHT 260828C55"}]},
    ]}
    monkeypatch.setattr(eng.chain, "get_chain_snapshot",
                        lambda symbol, expiration, option_type, max_contracts: chain)

    res = eng._affordable_contract("X", "CALL", budget=1000.0, expiration="2026-08-28")
    assert res is not None
    contract, cost, n = res
    leg = contract["Legs"][0]["Symbol"]
    assert leg == "TIGHT 260828C55", "selection took a wide, expensive-to-trade contract"


def test_all_wide_contracts_yield_no_selection(monkeypatch):
    """If every affordable contract is untradeably wide, select nothing rather than trade a
    guaranteed loser."""
    from app.services.momentum_options_execution_engine import MomentumOptionsExecutionEngine
    eng = MomentumOptionsExecutionEngine()
    chain = {"contracts": [
        {"Side": "Call", "Bid": 3.20, "Ask": 4.25, "Mid": 3.72, "Delta": 0.42,
         "DailyOpenInterest": 9000, "Strike": 60, "Legs": [{"Symbol": "WIDE 260828C60"}]},
    ]}
    monkeypatch.setattr(eng.chain, "get_chain_snapshot",
                        lambda symbol, expiration, option_type, max_contracts: chain)
    assert eng._affordable_contract("X", "CALL", budget=1000.0, expiration="2026-08-28") is None
