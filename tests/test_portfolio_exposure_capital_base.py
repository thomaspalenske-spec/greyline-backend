import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


def _engine(tmp_path, rows):
    equity = tmp_path / "paper_trade_ledger.jsonl"
    equity.write_text("".join(json.dumps(r) + "\n" for r in rows))

    eng = PortfolioExposureEngine()
    eng.equity_ledger = equity
    eng.option_ledger = tmp_path / "no_options.jsonl"
    # Hermetic: these tests exercise the capital-base math off the PAPER ledger only. Pin the broker
    # holdings to empty+healthy so a live/cached TradeStation read can't leak real positions into the
    # count when the suite runs alongside broker-touching tests. (Returns (rows, degraded).)
    eng._broker_positions = lambda: ([], False)
    return eng


def _equity(symbol, quantity, price):
    return {
        "status": "OPEN",
        "symbol": symbol,
        "asset_type": "EQUITY",
        "quantity": quantity,
        "entry_price": price,
    }


def test_single_position_is_not_treated_as_100_pct_concentration(tmp_path):
    # The 2026-07-14 zero-trade bug: sector exposure was a share of open notional,
    # so one position always read 100% and permanently hard-blocked new entries.
    # Against a $10k capital base, one ~$158 position is ~1.6%, not a breach.
    out = _engine(tmp_path, [_equity("XLV", 1, 158.29)]).evaluate()

    assert out["open_position_count"] == 1
    assert out["max_sector_exposure_pct_of_book"] == 100.0  # degenerate share-of-book
    assert out["max_sector_exposure_pct"] == 1.58           # share of capital
    assert out["max_sector_exposure_pct"] < 50
    assert out["concentration_risk"] == "LOW"


def test_genuine_sector_concentration_still_breaches(tmp_path):
    # The circuit breaker must still bite: $6,320 of healthcare on a $10k account
    # is 63.2% of capital and should be blocked.
    out = _engine(tmp_path, [_equity("XLV", 40, 158.0)]).evaluate()

    assert out["max_sector_exposure_pct"] == 63.2
    assert out["max_sector_exposure_pct"] >= 50
    assert out["concentration_risk"] == "HIGH"


def test_small_diversified_book_does_not_false_trip(tmp_path):
    # Two small positions in different sectors: one is 50% of the *book*, but only
    # 15.8% of capital. Share-of-book would have blocked this; capital-relative won't.
    out = _engine(tmp_path, [_equity("XLV", 10, 158.0), _equity("XLK", 10, 158.0)]).evaluate()

    assert out["max_sector_exposure_pct_of_book"] == 50.0
    assert out["max_sector_exposure_pct"] == 15.8
    assert out["max_sector_exposure_pct"] < 50


def test_capital_base_is_env_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "50000")
    out = _engine(tmp_path, [_equity("XLV", 40, 158.0)]).evaluate()

    # Same $6,320 position is only 12.64% of a $50k account.
    assert out["capital_base"] == 50000.0
    assert out["max_sector_exposure_pct"] == 12.64


def test_invalid_capital_base_falls_back_rather_than_disabling_breaker(tmp_path, monkeypatch):
    # A zero/garbage base must not divide the circuit breaker out of existence.
    for bad in ("0", "-100", "not_a_number"):
        monkeypatch.setenv("GREYLINE_ACCOUNT_CAPITAL_BASE", bad)
        out = _engine(tmp_path, [_equity("XLV", 40, 158.0)]).evaluate()
        assert out["capital_base"] == PortfolioExposureEngine.DEFAULT_CAPITAL_BASE
        assert out["max_sector_exposure_pct"] >= 50  # still breaches
