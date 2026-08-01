"""Budget-float sizing for the momentum sleeve (Option A).

The legacy sizing rule capped the book at a FIXED count of equal slots (top_n − held). At a
small book, whole-share rounding leaves each held name below its per-name target, so real sleeve
budget sits IDLE while the count still reads "full" — a cheap, high-conviction name (the BRUN
case) can't be secured though the % allocation isn't spent. Budget mode floats the name-count
under the %-of-equity budget: it deploys the unspent sleeve dollars into the top-ranked
affordable names. Gated by GREYLINE_MOMENTUM_BUDGET_SIZING (default on), revertible to "count".

Hermetic: universe/select/sector/regime/market all stubbed; the SIM booking is mocked so no
real order ever reaches the broker.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

MOD = "app.services.momentum_reversal_rebalance_engine"


def _t(sym, conv, px):
    return {"symbol": sym, "side": "BUY", "directional_bias": "BULLISH",
            "conviction": conv, "last_close": px}


def _run(tmp_path, monkeypatch, sizing, top_n=2, capital_base=1000.0):
    """Set up a rebalance where the sleeve's top_n slots are FULL but budget sits idle, then
    return (result, ledger). HELD1/HELD2 each consumed only $100 of a $500/name target, so
    ~$800 of the $1,000 sleeve budget is unspent. NEW is a cheap, lower-ranked affordable name."""
    import os
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    # A mid-suite .env reload re-populates GREYLINE_MOMENTUM_BUDGET_SIZING=true from .env and would
    # defeat a plain setenv("false") (the documented .env precedence trap). Patch the module's getenv
    # so the sizing flag reads deterministically, delegating every other key to the real environment.
    real_getenv = os.getenv
    monkeypatch.setattr(f"{MOD}.getenv",
                        lambda k, d="": sizing if k == "GREYLINE_MOMENTUM_BUDGET_SIZING" else real_getenv(k, d))

    eng = MomentumReversalRebalanceEngine(top_n=top_n)
    eng.strategy.capital_base = capital_base            # per_name = 1000/2 = $500
    eng.STATE = tmp_path / "state.json"
    led = PaperTradeLedgerEngine(); led.ledger_file = tmp_path / "ledger.jsonl"; eng.ledger = led

    # Pre-seed the sleeve FULL on count (2 held = top_n) but light on dollars ($100 each).
    for sym in ("HELD1", "HELD2"):
        led.open_trade(symbol=sym, side="BUY", quantity=1, entry_price=100.0,
                       directional_bias="BULLISH", trade_intent="MOMENTUM_REVERSAL",
                       direction_confidence=1.99)

    fresh = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    targets = [_t("HELD1", 1.99, 100.0), _t("HELD2", 1.98, 100.0), _t("NEW", 1.80, 50.0)]
    monkeypatch.setattr(eng.strategy, "universe",
                        lambda prefer_live=True: ({"X": [100.0]}, fresh, "TRADESTATION_LIVE"))
    monkeypatch.setattr(eng.strategy, "select", lambda series: (list(targets), list(targets)))
    monkeypatch.setattr(eng, "_staleness", lambda *a, **k: None)

    import app.services.portfolio_exposure_engine as pe
    monkeypatch.setattr(pe.PortfolioExposureEngine, "_sector", lambda self, s: "UNKNOWN")
    import app.services.market_regime_gate_engine as rg
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "assess",
                        lambda self: {"regime": "RISK_ON", "risk_off": False, "degraded": False})
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "enabled", staticmethod(lambda: True))

    m = patch(f"{MOD}.MarketHoursEngine")
    bk = patch("app.services.greyline_sim_execution_engine.GreyLineSimExecutionEngine")
    mm, bb = m.start(), bk.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    bb.return_value.book_opens.return_value = {"status": "MOCKED", "placed": 0}
    try:
        return eng.rebalance(force=True), led
    finally:
        m.stop(); bk.stop()


def test_budget_mode_deploys_idle_headroom_when_slots_full(tmp_path, monkeypatch):
    r, led = _run(tmp_path, monkeypatch, sizing="true")
    # Slots are full (free_slots == 0) but the sleeve has ~$800 idle → NEW is still opened.
    assert r["free_slots"] == 0
    assert r["sizing_mode"] == "budget"
    assert r["deploy_budget_usd"] == 800.0            # 1000 budget − 200 committed
    opened = {o["symbol"]: o for o in r["opened"]}
    assert "NEW" in opened, "budget mode must deploy idle headroom into the affordable next name"
    # sized at the per-name target ($500), capped by headroom → 10 whole shares @ $50
    assert opened["NEW"]["quantity"] == 10
    open_syms = {t["symbol"] for t in led._read_all() if t.get("status") == "OPEN"}
    assert open_syms == {"HELD1", "HELD2", "NEW"}     # book floated from 2 → 3 names


def test_legacy_count_mode_leaves_headroom_idle(tmp_path, monkeypatch):
    r, led = _run(tmp_path, monkeypatch, sizing="false")
    # Same idle budget, but count mode is full at top_n → opens NOTHING (the old behavior).
    assert r["free_slots"] == 0
    assert r["sizing_mode"] == "count"
    assert r["opened"] == []
    open_syms = {t["symbol"] for t in led._read_all() if t.get("status") == "OPEN"}
    assert open_syms == {"HELD1", "HELD2"}            # BRUN-equivalent left unsecured


def test_book_opens_honors_recorded_quantity(monkeypatch):
    """With unequal budget sizing, the SIM must book the ledger-RECORDED quantity, never a
    per_name re-derivation (that divergence is the dual-path phantom bug)."""
    from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
    eng = GreyLineSimExecutionEngine()
    monkeypatch.setattr(GreyLineSimExecutionEngine, "enabled", staticmethod(lambda: True))

    calls = []
    def _fake_place(symbol, shares, action="BUY", order_type="Market", tif="DAY"):
        calls.append({"symbol": symbol, "shares": shares})
        return {"ok": True, "order_id": "X", "http_status": 200}
    monkeypatch.setattr(eng.booking, "place_order", _fake_place)

    # per_name_notional=500 would derive 5 and 10 shares; the recorded quantities are 3 and 12.
    opens = [{"symbol": "AAA", "side": "BUY", "entry_price": 100.0, "quantity": 3},
             {"symbol": "BBB", "side": "BUY", "entry_price": 50.0, "quantity": 12}]
    out = eng.book_opens(opens, 500)
    booked = {c["symbol"]: c["shares"] for c in calls}
    assert booked == {"AAA": 3, "BBB": 12}, "SIM must book the recorded qty, not per_name-derived"
    assert out["placed"] == 2
