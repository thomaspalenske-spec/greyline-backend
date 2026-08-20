"""Hypothetical 100-share-lot sizing for the zero-capital shadows: contracts + total-dollar P/L, one
shared definition. Read-only, no orders."""

import app.services.shadow_contract_sizing as S


def test_default_contracts_and_env_override(monkeypatch):
    monkeypatch.delenv("GREYLINE_SHADOW_CONTRACTS", raising=False)
    assert S.default_contracts() == 1
    monkeypatch.setenv("GREYLINE_SHADOW_CONTRACTS", "3")
    assert S.default_contracts() == 3
    monkeypatch.setenv("GREYLINE_SHADOW_CONTRACTS", "0")     # floor at 1
    assert S.default_contracts() == 1
    monkeypatch.setenv("GREYLINE_SHADOW_CONTRACTS", "junk")  # bad value -> 1
    assert S.default_contracts() == 1


def test_pnl_dollars_scales_by_100_and_contracts():
    assert S.pnl_dollars(3.99) == 399.0          # 1 lot × 100
    assert S.pnl_dollars(3.99, 2) == 798.0       # 2 lots
    assert S.pnl_dollars(None) is None


def test_enrich_open_rows_is_side_aware(monkeypatch):
    monkeypatch.delenv("GREYLINE_SHADOW_CONTRACTS", raising=False)
    rows = [
        {"symbol": "AAA", "side": "BUY", "entry_close": 100.0, "live_last": 101.5},   # long winner
        {"symbol": "BBB", "side": "SELL", "entry_close": 50.0, "live_last": 48.0},    # short winner
        {"symbol": "CCC", "side": "BUY", "entry_close": 10.0, "live_last": None},     # no mark yet
    ]
    out = S.enrich_open_rows(rows)
    assert out[0]["contracts"] == 1 and out[0]["pnl_per_share"] == 1.5 and out[0]["pnl_dollars"] == 150.0
    assert out[1]["pnl_per_share"] == 2.0 and out[1]["pnl_dollars"] == 200.0   # short profits as price falls
    assert out[2]["contracts"] == 1 and "pnl_dollars" not in out[2]           # unpriced -> no fabricated P/L


def test_fx_usd_base_pair_converts_move_to_usd(monkeypatch):
    """USD-base pairs (USDJPY/USDCAD/USDCHF) quote the price in the FOREIGN currency, so the per-unit move is
    NOT dollars. Without conversion, USDJPY long 158.543->159.082 mislabels a 0.539-yen move as $53.90; the
    true USD value of the hypothetical 100-unit lot is ~$0.34 (the move divided by the live JPY rate)."""
    monkeypatch.delenv("GREYLINE_SHADOW_CONTRACTS", raising=False)
    row = {"symbol": "USDJPY", "side": "BUY", "entry_close": 158.543, "live_last": 159.082}
    S.enrich_open_rows([row], fx=True)
    assert row["pnl_dollars"] == 0.34                    # ¥53.9 / 159.082, NOT $53.90
    # fx=False (the equity/ETF path) leaves the same numbers as a raw price move -> the old (wrong-for-FX) $53.90
    eq = {"symbol": "USDJPY", "side": "BUY", "entry_close": 158.543, "live_last": 159.082}
    S.enrich_open_rows([eq])
    assert eq["pnl_dollars"] == 53.9


def test_fx_quote_is_usd_pair_unchanged(monkeypatch):
    """'...USD' pairs (EURUSD/GBPUSD/AUDUSD) are already quoted in USD, so the move IS dollars — no conversion.
    Long EURUSD 1.16758->1.16958 = +0.002 * 100 = $0.20, whether or not fx-marked."""
    monkeypatch.delenv("GREYLINE_SHADOW_CONTRACTS", raising=False)
    a = {"symbol": "EURUSD", "side": "BUY", "entry_close": 1.16758, "live_last": 1.16958}
    b = {"symbol": "EURUSD", "side": "BUY", "entry_close": 1.16758, "live_last": 1.16958}
    S.enrich_open_rows([a], fx=True)
    S.enrich_open_rows([b])
    assert a["pnl_dollars"] == b["pnl_dollars"] == 0.2


def test_futures_rows_carry_no_fabricated_dollars(monkeypatch):
    """Futures have per-contract point values (ES $50/pt, ZB $1000/pt, grains in cents) and roll gaps on the
    continuous series, so a share-style (move x 100) dollar is meaningless. dollars=False keeps the contract
    count + raw move but attaches NO pnl_dollars — the % return is the measurement (point value deferred to arm)."""
    monkeypatch.delenv("GREYLINE_SHADOW_CONTRACTS", raising=False)
    row = {"symbol": "ES", "side": "BUY", "entry_close": 5000.0, "live_last": 5010.0}
    S.enrich_open_rows([row], dollars=False)
    assert row["contracts"] == 1                    # 1 contract is meaningful for a future
    assert row["pnl_per_share"] == 10.0             # raw point move kept for context
    assert "pnl_dollars" not in row                 # NO fabricated dollar (would have been a bogus $1000)
    assert "pnl_dollars_na" in row                  # reason attached instead
