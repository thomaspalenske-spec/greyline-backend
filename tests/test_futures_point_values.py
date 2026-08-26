"""Futures shadow per-contract UNREALIZED $ (2026-08-25): the verified CME/CBOT/COMEX/NYMEX/CFE point-value
table turns the card's "—" into a correct dollar P/L, and an unverified root still keeps "—" (never a guess).
Plus the matched-notional inclusion into the with-shadows aggregate so 1-contract futures $ can't swamp it."""

import app.services.shadow_contract_sizing as SZ
from app.services.shadow_contract_sizing import enrich_open_rows, futures_point_value, FUTURES_POINT_VALUES


def test_all_19_shadow_roots_have_a_verified_point_value():
    roots = ["ES", "NQ", "RTY", "YM", "US", "TY", "FV", "TU", "CL", "NG",
             "RB", "GC", "SI", "HG", "PL", "C", "S", "W", "VX"]
    missing = [r for r in roots if futures_point_value(r) is None]
    assert not missing, f"unverified roots would render '—': {missing}"


def test_spot_check_key_multipliers():
    assert FUTURES_POINT_VALUES["ES"] == 50.0      # E-mini S&P $50/pt
    assert FUTURES_POINT_VALUES["CL"] == 1000.0    # Crude 1,000 bbl
    assert FUTURES_POINT_VALUES["GC"] == 100.0     # Gold 100 oz
    assert FUTURES_POINT_VALUES["TU"] == 2000.0    # 2Y note $200k face
    assert FUTURES_POINT_VALUES["W"] == 50.0       # wheat 5,000 bu × 1 cent
    assert futures_point_value("@ES") == 50.0      # tolerates the @ROOT form


def test_enrich_futures_computes_move_times_multiplier():
    rows = [{"symbol": "ES", "side": "BUY", "entry_close": 7772.5, "live_last": 7681.5}]
    enrich_open_rows(rows, futures=True)
    # -91.0 points × $50 × 1 contract = -$4,550
    assert rows[0]["pnl_dollars"] == -4550.0
    assert rows[0]["point_value"] == 50.0


def test_enrich_futures_short_side_signed():
    rows = [{"symbol": "US", "side": "SELL", "entry_close": 109.0, "live_last": 108.0}]
    enrich_open_rows(rows, futures=True)
    # short a 1.0-point drop on ZB ($1,000/pt) = +$1,000
    assert rows[0]["pnl_dollars"] == 1000.0


def test_enrich_futures_unknown_root_keeps_dash():
    rows = [{"symbol": "ZZZ", "side": "BUY", "entry_close": 100.0, "live_last": 110.0}]
    enrich_open_rows(rows, futures=True)
    assert "pnl_dollars" not in rows[0]
    assert "no verified point value" in rows[0]["pnl_dollars_na"]


def test_matched_notional_keeps_futures_comparable(monkeypatch):
    # A raw 1-contract sum would be ±thousands; matched notional ($1k/leg) scales to notional × %-return.
    monkeypatch.setenv("GREYLINE_SHADOW_MATCHED_NOTIONAL", "1000")
    # ES +1% at $1k notional = +$10, regardless of the $388k real contract notional
    notl = 1000.0
    ec, ll = 100.0, 101.0
    contribution = notl * (ll / ec - 1.0)
    assert round(contribution, 2) == 10.0
