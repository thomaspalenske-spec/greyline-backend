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
