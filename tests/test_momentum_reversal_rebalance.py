import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

MOD = "app.services.momentum_reversal_rebalance_engine"


def _confirmed_bullish():
    c = [100.0] * 260
    c[-253] = 90.0     # 12mo-ago low -> bullish momentum
    c[-22] = 100.0
    c[-6] = 101.0      # recent move down -> reversal bullish (agrees)
    c[-1] = 100.0
    return c


def _confirmed_bearish():
    c = [100.0] * 260
    c[-253] = 110.0    # 12mo-ago high -> bearish momentum (fell over the year)
    c[-22] = 100.0
    c[-6] = 99.0       # recent move up -> reversal bearish (agrees)
    c[-1] = 100.0
    return c


def test_blocked_when_execution_disabled(monkeypatch):
    import os
    # The engine reads GREYLINE_PAPER_EXECUTION_ENABLED via its module-level getenv, and a .env reload
    # (triggered by other engines mid-suite) re-populates it into os.environ — defeating a plain delenv
    # (the documented .env precedence trap; .env ships PAPER_EXECUTION=true for SIM booking). Patch the
    # module's getenv so the paper-exec gate reads OFF deterministically, independent of os.environ/.env.
    real = os.getenv
    monkeypatch.setattr(f"{MOD}.getenv",
                        lambda k, d="": "" if k == "GREYLINE_PAPER_EXECUTION_ENABLED" else real(k, d))
    out = MomentumReversalRebalanceEngine().rebalance(force=True)
    assert out["rebalanced"] is False
    assert "EXECUTION_DISABLED" in out["status"]


def test_skipped_when_not_due(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    eng = MomentumReversalRebalanceEngine()
    eng.STATE = tmp_path / "state.json"
    eng.STATE.write_text('{"last_rebalance_at": "%s"}' % datetime.utcnow().isoformat())
    with patch(f"{MOD}.MarketHoursEngine") as M:
        M.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
        out = eng.rebalance(force=False)   # not forced -> honors the schedule
    assert out["rebalanced"] is False
    assert out["status"] == "REBALANCE_SKIPPED_NOT_DUE"


def _sandbox(tmp_path, monkeypatch, universe):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    eng = MomentumReversalRebalanceEngine(top_n=2)
    eng.STATE = tmp_path / "state.json"
    led = PaperTradeLedgerEngine()
    led.ledger_file = tmp_path / "ledger.jsonl"
    eng.ledger = led
    # Use a live source + recent as-of so the stale-data guard lets the trade through.
    from datetime import datetime, timedelta
    fresh = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    monkeypatch.setattr(eng.strategy, "universe",
                        lambda prefer_live=True: (universe, fresh, "TRADESTATION_LIVE"))
    m = patch(f"{MOD}.MarketHoursEngine")
    lim = patch(f"{MOD}.PositionExposureLimitEngine")
    # The rebalance BOOKS to the broker. Unmocked, this test bought 50 shares each of the
    # fake symbols AAA/BBB in the real Paper Trading Account on every run once SIM booking
    # was enabled. Assert on the ledger, never on the wire.
    book = patch("app.services.greyline_sim_execution_engine.GreyLineSimExecutionEngine")
    bb = book.start()
    bb.return_value.book_opens.return_value = {"status": "SIM_BOOKING_MOCKED", "placed": 0}
    mm, ll = m.start(), lim.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    ll.return_value.evaluate.return_value = {"limits_ok": True}
    monkeypatch.setattr("app.services.momentum_reversal_strategy_engine.PositionExposureLimitEngine",
                        ll)  # keep any strategy-side check consistent
    return eng, led, (m, lim, book)


def test_rebalance_opens_into_free_slots_only(tmp_path, monkeypatch):
    # top_n=3 (set in _sandbox); two confirmed signals -> open both, 1 slot left.
    uni = {"AAA": _confirmed_bullish(), "BBB": _confirmed_bullish()}
    eng, led, patches = _sandbox(tmp_path, monkeypatch, uni)
    try:
        r1 = eng.rebalance(force=True)
        assert r1["rebalanced"] is True
        assert len(r1["opened"]) == 2
        opens = [t for t in led._read_all() if t.get("status") == "OPEN"]
        assert len(opens) == 2
        assert all(t["trade_intent"] == "MOMENTUM_REVERSAL" for t in opens)

        # H2 owns exits now: the rebalance does NOT close held positions, and it does
        # NOT re-open symbols already held. AAA/BBB are held -> nothing new to open.
        r2 = eng.rebalance(force=True)
        assert r2["opened"] == []
        assert r2["held_before"] == 2
        still_open = [t for t in led._read_all() if t.get("status") == "OPEN"]
        assert len(still_open) == 2   # unchanged — not churned
    finally:
        for p in patches:
            p.stop()


def test_rebalance_is_long_only_and_regime_gated(tmp_path, monkeypatch):
    """2026-07-24 backtest verdict wired in: the equity path trades LONG ONLY (short side is
    survivorship noise) and applies the regime gate (no dip-buys when SPY < 200DMA)."""
    # one bullish (buy-the-dip in uptrend) and one bearish target from the strategy
    uni = {"BULL": _confirmed_bullish(), "BEAR": _confirmed_bearish()}
    eng, led, patches = _sandbox(tmp_path, monkeypatch, uni)
    try:
        # RISK_ON regime -> bullish longs allowed, bearish dropped
        import app.services.market_regime_gate_engine as rg
        monkeypatch.setattr(rg.MarketRegimeGateEngine, "assess",
                            lambda self: {"regime": "RISK_ON", "risk_off": False, "degraded": False})
        monkeypatch.setattr(rg.MarketRegimeGateEngine, "enabled", staticmethod(lambda: True))
        r = eng.rebalance(force=True)
        opened_syms = {t["symbol"] for t in r["opened"]}
        assert "BEAR" not in opened_syms, "short/bearish name must never be opened (long-only)"
        assert r.get("long_only") is True
    finally:
        for p in patches:
            p.stop()


def test_rebalance_risk_off_opens_nothing(tmp_path, monkeypatch):
    """RISK_OFF (SPY below 200DMA): dip-buying is blocked, and shorts are already excluded, so
    the equity path opens NOTHING — exactly the 2008 protection the backtest motivates."""
    uni = {"BULL": _confirmed_bullish(), "BULL2": _confirmed_bullish()}
    eng, led, patches = _sandbox(tmp_path, monkeypatch, uni)
    try:
        import app.services.market_regime_gate_engine as rg
        monkeypatch.setattr(rg.MarketRegimeGateEngine, "assess",
                            lambda self: {"regime": "RISK_OFF", "risk_off": True, "degraded": False})
        monkeypatch.setattr(rg.MarketRegimeGateEngine, "enabled", staticmethod(lambda: True))
        r = eng.rebalance(force=True)
        assert r["opened"] == []
        assert r.get("regime_blocked", 0) >= 1
    finally:
        for p in patches:
            p.stop()


def test_sector_cap_skips_and_diversifies_instead_of_breaking(tmp_path, monkeypatch):
    """Momentum clusters by sector. When one sector hits its cap, the rebalance must SKIP the
    excess names and keep filling the book with OTHER sectors — not break the loop and leave a
    small concentrated cluster. Hermetic: select() is stubbed so the test isolates the sector
    logic, not the signal ranking."""
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_MAX_SECTOR_EXPOSURE_PCT", "50")
    from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
    from datetime import datetime, timedelta
    from unittest.mock import patch

    eng = MomentumReversalRebalanceEngine(top_n=6)   # max 3 per sector (50% of 6)
    eng.STATE = tmp_path / "state.json"
    led = PaperTradeLedgerEngine(); led.ledger_file = tmp_path / "ledger.jsonl"; eng.ledger = led
    fresh = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    # 4 tech then 2 diversifiers, DISTINCT descending conviction so order is deterministic
    def _t(sym, conv):
        return {"symbol": sym, "side": "BUY", "directional_bias": "BULLISH",
                "conviction": conv, "last_close": 100.0}
    fixed = [_t("TECH0", 1.99), _t("TECH1", 1.98), _t("TECH2", 1.97), _t("TECH3", 1.96),
             _t("HEALTH1", 1.95), _t("INDU1", 1.94)]
    monkeypatch.setattr(eng.strategy, "universe",
                        lambda prefer_live=True: ({"X": [100.0]}, fresh, "TRADESTATION_LIVE"))
    monkeypatch.setattr(eng.strategy, "select", lambda series: (list(fixed), list(fixed)))

    sectors = {"TECH0": "TECHNOLOGY", "TECH1": "TECHNOLOGY", "TECH2": "TECHNOLOGY",
               "TECH3": "TECHNOLOGY", "HEALTH1": "HEALTHCARE", "INDU1": "INDUSTRIALS"}
    import app.services.portfolio_exposure_engine as pe
    monkeypatch.setattr(pe.PortfolioExposureEngine, "_sector",
                        lambda self, s: sectors.get(s, "UNKNOWN"))
    import app.services.market_regime_gate_engine as rg
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "assess",
                        lambda self: {"regime": "RISK_ON", "risk_off": False, "degraded": False})
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(eng, "_staleness", lambda *a, **k: None)

    m = patch("app.services.momentum_reversal_rebalance_engine.MarketHoursEngine")
    bk = patch("app.services.greyline_sim_execution_engine.GreyLineSimExecutionEngine")
    mm, bb = m.start(), bk.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    bb.return_value.book_opens.return_value = {"status": "MOCKED", "placed": 0}
    try:
        r = eng.rebalance(force=True)
        opened = {o["symbol"] for o in r["opened"]}
        tech_opened = sum(1 for x in opened if sectors[x] == "TECHNOLOGY")
        assert tech_opened <= 3, f"tech not capped at 50%: {opened}"
        assert opened & {"HEALTH1", "INDU1"}, f"loop broke before diversifying: {opened}"
        assert "TECH3" not in opened, f"4th tech should be skipped (sector full): {opened}"
    finally:
        m.stop(); bk.stop()


def test_point_in_time_vol_ceiling_drops_wild_names_without_biasing_the_universe(tmp_path, monkeypatch):
    """Volatility control must be a TRAILING-DATA rule at decision time — never a universe
    screen on full-sample vol (that deletes names retroactively using information the strategy
    could not have had). A wild name is skipped; a calm one trades; the universe is untouched."""
    import random
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_MAX_TRAILING_VOL_PCT", "100")
    from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
    from datetime import datetime, timedelta
    from unittest.mock import patch

    eng = MomentumReversalRebalanceEngine(top_n=4)
    eng.STATE = tmp_path / "s.json"
    led = PaperTradeLedgerEngine(); led.ledger_file = tmp_path / "l.jsonl"; eng.ledger = led

    calm = [100 * (1.001 ** i) for i in range(300)]          # ~0% vol
    rng = random.Random(3)
    wild = [100.0]
    for _ in range(300):
        wild.append(wild[-1] * (1 + rng.gauss(0, 0.09)))     # ~140% vol
    series = {"CALM": calm, "WILD": wild}
    fresh = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    def _t(sym):
        return {"symbol": sym, "side": "BUY", "directional_bias": "BULLISH",
                "conviction": 1.9, "last_close": 100.0}
    monkeypatch.setattr(eng.strategy, "universe",
                        lambda prefer_live=True: (series, fresh, "TRADESTATION_LIVE"))
    monkeypatch.setattr(eng.strategy, "select",
                        lambda s: ([_t("WILD"), _t("CALM")], [_t("WILD"), _t("CALM")]))
    monkeypatch.setattr(eng, "_staleness", lambda *a, **k: None)
    import app.services.market_regime_gate_engine as rg
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "assess",
                        lambda self: {"regime": "RISK_ON", "risk_off": False, "degraded": False})
    monkeypatch.setattr(rg.MarketRegimeGateEngine, "enabled", staticmethod(lambda: True))
    import app.services.portfolio_exposure_engine as pe
    monkeypatch.setattr(pe.PortfolioExposureEngine, "_sector", lambda self, s: "TECHNOLOGY")

    m = patch("app.services.momentum_reversal_rebalance_engine.MarketHoursEngine")
    bk = patch("app.services.greyline_sim_execution_engine.GreyLineSimExecutionEngine")
    mm, bb = m.start(), bk.start()
    mm.return_value.status.return_value = {"is_regular_session": True, "state": "OPEN"}
    bb.return_value.book_opens.return_value = {"status": "MOCKED", "placed": 0}
    try:
        r = eng.rebalance(force=True)
        opened = {o["symbol"] for o in r["opened"]}
        assert "WILD" not in opened, f"wild name should be vol-blocked: {opened}"
        assert "CALM" in opened, f"calm name should trade: {opened}"
        assert r["vol_blocked"] == 1
    finally:
        m.stop(); bk.stop()
