"""The regime gate must block dip-buys ONLY in a real downtrend, only bullish ones, and must
never invent or force a trade. Tail-risk protection, not a signal."""

import csv

import pytest

from app.services.market_regime_gate_engine import MarketRegimeGateEngine

HDR = "date,open,high,low,close,volume\n"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(MarketRegimeGateEngine, "HIST_DIR", tmp_path)
    monkeypatch.setenv("GREYLINE_REGIME_GATE_ENABLED", "true")
    return MarketRegimeGateEngine()


def _spy(tmp_path, closes, last_date=None):
    """Write a SPY series ending on a recent date (default: TODAY, so freshness checks pass
    regardless of the calendar) with the given closes."""
    from datetime import date, datetime, timedelta
    end = date.fromisoformat(last_date) if last_date else datetime.utcnow().date()
    rows = []
    for i, c in enumerate(closes):
        d = end - timedelta(days=(len(closes) - 1 - i))
        rows.append(f"{d.isoformat()},{c},{c},{c},{c},1000000\n")
    (tmp_path / "SPY_daily.csv").write_text(HDR + "".join(rows))


def _targets():
    return [{"symbol": "AAA", "directional_bias": "BULLISH", "side": "BUY"},
            {"symbol": "BBB", "directional_bias": "BEARISH", "side": "SELL"}]


def test_risk_on_keeps_everything(gate, tmp_path):
    """Price well above the 200DMA -> normal dip-buying regime, nothing blocked."""
    _spy(tmp_path, [100.0] * 200 + [130.0])          # last close far above the flat 200DMA
    kept, dropped, regime = gate.filter_targets(_targets())
    assert regime["regime"] == "RISK_ON"
    assert len(kept) == 2 and dropped == []


def test_risk_off_blocks_bullish_keeps_bearish(gate, tmp_path):
    """Below the 200DMA -> block the dip-buy (call), keep the bearish (put) setup."""
    _spy(tmp_path, [100.0] * 200 + [80.0])           # last close below the 200DMA
    kept, dropped, regime = gate.filter_targets(_targets())
    assert regime["regime"] == "RISK_OFF"
    assert [t["symbol"] for t in kept] == ["BBB"]     # bearish survives
    assert [d["symbol"] for d in dropped] == ["AAA"]  # bullish dropped


def test_disabled_gate_is_a_passthrough(gate, tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_REGIME_GATE_ENABLED", "false")
    _spy(tmp_path, [100.0] * 200 + [80.0])           # would be RISK_OFF...
    kept, dropped, regime = gate.filter_targets(_targets())
    assert len(kept) == 2 and dropped == []           # ...but the gate is off
    assert regime["gate_enabled"] is False


def test_missing_index_fails_open_not_closed(gate, tmp_path):
    """No SPY file -> the gate must NOT halt trading; it allows all and flags degraded."""
    kept, dropped, regime = gate.filter_targets(_targets())
    assert len(kept) == 2 and dropped == []
    assert regime["degraded"] is True


def test_stale_index_is_not_trusted(gate, tmp_path):
    """An old index bar can't describe today's regime -> degrade, fail open."""
    _spy(tmp_path, [100.0] * 200 + [80.0], last_date="2026-01-01")   # months stale
    _, dropped, regime = gate.filter_targets(_targets())
    assert regime["degraded"] is True and dropped == []
