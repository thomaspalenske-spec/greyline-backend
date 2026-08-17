"""Hermetic tests for HarvestProofEngine — synthetic ledgers, no I/O on the real file.

Verifies it measures realized trades honestly: correct aggregates, adaptive-vs-static and richness
splits, exit-reason tally, and that it refuses to claim significance below MIN_FOR_SIGNAL.
"""

from app.services.harvest_proof_engine import HarvestProofEngine as ENG


def _closed(symbol, pnl, credit, max_loss, mode, iv_rank, entry_dte, reason,
            opened="2026-08-01T14:00:00", closed="2026-08-15T14:00:00"):
    return {"symbol": symbol, "status": "CLOSED", "realized_pnl": pnl, "credit_total": credit,
            "max_loss_total": max_loss, "dte_selection_mode": mode, "entry_iv_rank": iv_rank,
            "entry_dte": entry_dte, "close_reason": reason, "opened_at": opened, "closed_at": closed}


def _open(symbol, max_loss):
    return {"symbol": symbol, "status": "OPEN", "max_loss_total": max_loss}


def _engine(rows, monkeypatch):
    eng = ENG()
    monkeypatch.setattr(eng, "_rows", lambda: rows)
    return eng


def test_no_trades_is_honest(monkeypatch):
    s = _engine([], monkeypatch).status()
    assert s["closed_trades"] == 0
    assert "NO CLOSED TRADES" in s["verdict"]


def test_open_positions_and_deployed_risk(monkeypatch):
    rows = [_open("SPY 1", 300.0), _open("IWM 1", 250.0)]
    s = _engine(rows, monkeypatch).status()
    assert s["open_positions"] == 2
    assert s["open_deployed_risk_usd"] == 550.0
    assert s["closed_trades"] == 0


def test_overall_aggregates(monkeypatch):
    rows = [
        _closed("A", 50.0, 100.0, 300.0, "adaptive", 0.9, 40, "PROFIT_TAKE_50PCT"),
        _closed("B", -120.0, 90.0, 300.0, "adaptive", 0.7, 35, "HARD_STOP_NEAR_MAX_LOSS"),
        _closed("C", 40.0, 80.0, 250.0, "static", 0.85, 42, "PROFIT_TAKE_50PCT"),
    ]
    s = _engine(rows, monkeypatch).status()
    o = s["overall"]
    assert o["n"] == 3
    assert o["total_realized_pnl"] == -30.0
    assert o["win_rate"] == round(2 / 3, 3)
    assert o["underpowered"] is True          # 3 < MIN_FOR_SIGNAL
    assert "UNDERPOWERED" in s["verdict"]


def test_splits_by_mode_and_richness_and_reason(monkeypatch):
    rows = [
        _closed("A", 50.0, 100.0, 300.0, "adaptive", 0.90, 40, "PROFIT_TAKE_50PCT"),
        _closed("B", 30.0, 90.0, 300.0, "adaptive", 0.70, 35, "MANAGE_DTE_21D"),
        _closed("C", -60.0, 80.0, 250.0, "static", 0.85, 42, "HARD_STOP_NEAR_MAX_LOSS"),
    ]
    s = _engine(rows, monkeypatch).status()
    # mode split
    assert s["by_dte_selection_mode"]["adaptive"]["n"] == 2
    assert s["by_dte_selection_mode"]["static"]["n"] == 1
    # richness split at 0.80: A(0.90),C(0.85) richest ; B(0.70) rich
    assert s["by_entry_richness"]["iv_rank_>=0.8"]["n"] == 2
    assert s["by_entry_richness"]["iv_rank_0.67-0.8"]["n"] == 1
    # reason tally
    assert s["by_close_reason"]["PROFIT_TAKE_50PCT"]["n"] == 1
    assert s["by_close_reason"]["HARD_STOP_NEAR_MAX_LOSS"]["pnl"] == -60.0


def test_credit_capture_and_ror(monkeypatch):
    rows = [_closed("A", 50.0, 100.0, 200.0, "adaptive", 0.9, 40, "PROFIT_TAKE_50PCT")]
    o = _engine(rows, monkeypatch).status()["overall"]
    assert o["avg_credit_capture"] == 0.5      # 50 / 100
    assert o["avg_return_on_risk"] == 0.25     # 50 / 200
    assert o["avg_hold_days"] == 14.0          # Aug 1 -> Aug 15


def test_readable_above_threshold(monkeypatch):
    rows = [_closed(f"S{i}", 10.0, 50.0, 200.0, "adaptive", 0.9, 40, "PROFIT_TAKE_50PCT")
            for i in range(ENG.MIN_FOR_SIGNAL)]
    s = _engine(rows, monkeypatch).status()
    assert s["overall"]["underpowered"] is False
    assert "READABLE" in s["verdict"]
