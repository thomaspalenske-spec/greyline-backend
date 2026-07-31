"""Root B: options sizing draws on the SHARED cross-book cash, and committed cost is never erased.

No network, no orders — the resolver and ledger file are controlled directly.
"""

import json

from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine


def test_account_free_cash_uses_the_cross_book_resolver(monkeypatch):
    monkeypatch.setattr(SleeveCapitalBudgetEngine, "_live",
                        classmethod(lambda cls: (9968.0, 3200.0)))     # (equity, deployable cash)
    assert OptionsPaperTradeLedgerEngine().account_free_cash() == 3200.0


def test_falls_back_to_both_book_cost_basis_when_broker_degraded(monkeypatch):
    monkeypatch.setattr(SleeveCapitalBudgetEngine, "_live",
                        classmethod(lambda cls: (9968.0, None)))       # degraded read → None cash
    eng = OptionsPaperTradeLedgerEngine()
    monkeypatch.setattr(eng, "_open_deployed_capital", lambda: 1000.0)
    monkeypatch.setattr(eng, "_equity_book_deployed", lambda: 2000.0)  # BOTH books subtracted
    monkeypatch.setattr(eng, "_closed_realized_pnl", lambda: -500.0)
    assert eng.account_free_cash(account_base=10000.0) == 6500.0        # 10000 - 500 - 3000


def test_underwater_open_option_still_counts_as_deployed(tmp_path):
    eng = OptionsPaperTradeLedgerEngine()
    eng.ledger_file = tmp_path / "opt.jsonl"
    eng.ledger_file.write_text(json.dumps({
        "status": "OPEN", "estimated_cost": 250.0,
        "manager_status": "OPTION_MARKET_CLOSED_LAST_QUOTE_MARK", "unrealized_pnl_pct": -40.0}) + "\n")
    # Previously this position was dropped (freeing $250 of imaginary cash); now its cost is committed.
    assert eng._open_deployed_capital() == 250.0
