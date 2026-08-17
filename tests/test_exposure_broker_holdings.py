"""The concentration cap must see ACTUAL broker holdings (the ETF sleeves book straight to the broker),
deduped against the paper ledger, with the cash sweep excluded (cash-equivalent, not a sector bet).

No network — the broker view is monkeypatched.
"""

import json

import app.services.broker_account_view_engine as bav
from app.services.portfolio_exposure_engine import PortfolioExposureEngine


def _broker(monkeypatch, positions):
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "snapshot",
                        lambda self: {"reads_ok": True, "positions": positions})


def test_broker_sleeve_holdings_enter_the_cap_and_cash_sweep_is_excluded(monkeypatch, tmp_path):
    eng = PortfolioExposureEngine()
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    eng.equity_ledger = empty
    eng.option_ledger = empty
    _broker(monkeypatch, [
        {"symbol": "DBC", "quantity": 12, "current_price": 29.0},     # ETF sleeve → must count
        {"symbol": "SGOV", "quantity": 72, "current_price": 100.0},   # cash sweep → must be excluded
        {"symbol": "SVXY", "quantity": 16, "current_price": 57.0},
    ])
    ev = eng.evaluate()
    syms = {p["symbol"] for p in ev["positions"]}
    assert "DBC" in syms and "SVXY" in syms          # broker holdings now visible to the cap
    assert "SGOV" not in syms                          # cash-equivalent, not a treasury concentration
    se = ev["sector_exposure"]
    assert "COMMODITIES" in se and "VOLATILITY" in se and "TREASURIES" not in se


def test_broker_holding_not_double_counted_when_already_in_ledger(monkeypatch, tmp_path):
    eng = PortfolioExposureEngine()
    led = tmp_path / "eq.jsonl"
    led.write_text(json.dumps({"status": "OPEN", "symbol": "AAPL", "quantity": 2,
                               "entry_price": 200.0, "asset_type": "EQUITY"}) + "\n")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    eng.equity_ledger = led
    eng.option_ledger = empty
    _broker(monkeypatch, [{"symbol": "AAPL", "quantity": 2, "current_price": 210.0}])
    ev = eng.evaluate()
    aapl = [p for p in ev["positions"] if p["symbol"] == "AAPL"]
    assert len(aapl) == 1                              # ledger wins; broker duplicate not added again


def test_degraded_broker_read_falls_back_to_ledger_only(monkeypatch, tmp_path):
    eng = PortfolioExposureEngine()
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    eng.equity_ledger = empty
    eng.option_ledger = empty
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "snapshot",
                        lambda self: {"reads_ok": False, "positions": [{"symbol": "DBC", "quantity": 1,
                                                                        "current_price": 29.0}]})
    ev = eng.evaluate()
    assert ev["positions"] == []                       # never trust a degraded read
