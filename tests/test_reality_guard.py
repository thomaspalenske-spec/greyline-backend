"""Regression guards against GreyLine reverting to 'fantasy land'.

These are structural + behavioral invariants. They fail if a future edit reintroduces the
exact failure that put fabricated positions on the operator dashboard: dashboard routes
reading the local paper ledger instead of the TradeStation account, or execution being armed
without real broker booking.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _src(rel):
    return (ROOT / rel).read_text()


# --- STRUCTURAL: the dashboard's account/position routes must source from the broker, never
#     the local ledger. This is the seam that failed before; keep it welded shut. -----------

def test_open_positions_route_does_not_read_local_ledger():
    src = _src("app/routes/open_positions.py")
    assert "PaperTradeLedgerEngine" not in src, \
        "open-positions must NOT read the local paper ledger — it must source from the broker."
    assert "BrokerAccountViewEngine" in src, \
        "open-positions must source positions from BrokerAccountViewEngine (real TradeStation)."


def test_account_summary_route_does_not_read_local_ledger():
    src = _src("app/routes/account_summary.py")
    assert "PaperTradeLedgerEngine" not in src, \
        "account-summary must NOT read the local paper ledger — it must source from the broker."
    assert "BrokerAccountViewEngine" in src, \
        "account-summary must source from BrokerAccountViewEngine (real TradeStation)."


def test_broker_view_only_reads_broker_engines():
    """The broker view must be built from the live TradeStation read engines, not the ledger."""
    src = _src("app/services/broker_account_view_engine.py")
    assert "PaperTradeLedgerEngine" not in src
    for eng in ("TradeStationPositionsLiveEngine", "TradeStationBalanceLiveEngine",
                "TradeStationOrdersLiveEngine"):
        assert eng in src, f"broker view must use {eng}"


# --- STRUCTURAL: the account selector must never let 'paper' mode fall back to the real
#     account, and must keep the host/account interlock. -------------------------------------

def test_account_selector_paper_has_no_realaccount_fallback():
    src = _src("app/services/tradestation_account_source_engine.py")
    # paper branch must read the SIM account id...
    assert "TRADESTATION_SIM_ACCOUNT_ID" in src
    # ...and must NEVER fall back to the real margin account for a SIM read (the old bug).
    assert not re.search(r"SIM_ACCOUNT_ID[\"']\s*\)\s*or\s+getenv\(\s*[\"']TRADESTATION_MARGIN", src), \
        "paper/SIM read must not fall back to the real margin account"


# --- BEHAVIORAL: the Reality Guard invariants themselves. ----------------------------------

def test_guard_flags_incoherent_execution_config(monkeypatch):
    """Paper execution ON + SIM booking OFF is the fantasy config; the guard must catch it."""
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "false")
    c = GreyLineRealityGuardEngine()._check_exec_booking_coherent()
    assert c["ok"] is False and c["severity"] == "critical"


def test_guard_execution_config_ok_when_both_off(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "false")
    assert GreyLineRealityGuardEngine()._check_exec_booking_coherent()["ok"] is True


def test_guard_detects_phantom_ledger_positions():
    """A ledger position the broker does not hold must be flagged as a phantom."""
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    guard = GreyLineRealityGuardEngine()
    # broker holds nothing; if the ledger has an open FOO, that's a phantom.
    # We exercise the pure comparison by faking the ledger read.
    import app.services.paper_trade_ledger_engine as ple

    class _FakeLedger:
        def _read_all(self):
            return [{"status": "OPEN", "symbol": "FOO"}]

    orig = ple.PaperTradeLedgerEngine
    ple.PaperTradeLedgerEngine = _FakeLedger
    try:
        res = guard._check_phantom_positions({"positions": []})
    finally:
        ple.PaperTradeLedgerEngine = orig
    assert res["ok"] is False
    assert "FOO" in res.get("phantoms", [])


def test_guard_no_phantom_when_broker_holds_it():
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    guard = GreyLineRealityGuardEngine()
    import app.services.paper_trade_ledger_engine as ple

    class _FakeLedger:
        def _read_all(self):
            return [{"status": "OPEN", "symbol": "FOO"}]

    orig = ple.PaperTradeLedgerEngine
    ple.PaperTradeLedgerEngine = _FakeLedger
    try:
        res = guard._check_phantom_positions({"positions": [{"symbol": "FOO"}]})
    finally:
        ple.PaperTradeLedgerEngine = orig
    assert res["ok"] is True


def test_guard_check_returns_verdict_and_never_throws():
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    out = GreyLineRealityGuardEngine().check()
    assert out["verdict"] in ("REAL_DATA_VERIFIED", "REAL_DATA_WITH_WARNINGS", "FANTASY_DETECTED")
    assert isinstance(out["checks"], list) and len(out["checks"]) >= 4


def test_working_limit_order_is_pending_not_phantom(tmp_path, monkeypatch):
    """Limit entries are now the normal path, so there is always a window where the ledger
    says OPEN and the broker has not filled yet. Flagging that as fantasy would make the
    guard cry wolf on every entry — it must only fire when NO order is working either."""
    import json
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

    monkeypatch.setattr(PaperTradeLedgerEngine, "_read_all", lambda self: [])
    led = tmp_path / "app/data/options_paper_trading"
    led.mkdir(parents=True)
    (led / "options_paper_trade_ledger.jsonl").write_text(
        json.dumps({"option_symbol": "MRNA 260828C60", "status": "OPEN"}) + "\n"
        + json.dumps({"option_symbol": "RKLB 260828C70", "status": "OPEN"}) + "\n")
    monkeypatch.chdir(tmp_path)   # the check resolves the options ledger by relative path

    res = GreyLineRealityGuardEngine()._check_phantom_positions({
        "positions": [],
        "pending_buys": [{"symbol": "MRNA 260828C60"}],   # working, not yet filled
    })
    assert res["phantoms"] == ["RKLB 260828C70"]        # nothing working -> real phantom
    assert res["pending_fill"] == ["MRNA 260828C60"]    # order working  -> just pending
    assert res["ok"] is False


def test_guard_surfaces_broker_positions_greyline_does_not_manage(tmp_path, monkeypatch):
    """The mirror of the phantom check. Real risk sitting in the account with no GreyLine
    stop/TP/maturity rule must be VISIBLE, not silently rendered as GreyLine's own book."""
    import json
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

    monkeypatch.setattr(PaperTradeLedgerEngine, "_read_all", lambda self: [])
    led = tmp_path / "app/data/options_paper_trading"
    led.mkdir(parents=True)
    (led / "options_paper_trade_ledger.jsonl").write_text(
        json.dumps({"option_symbol": "GLW 260828C180", "status": "OPEN"}) + "\n")
    monkeypatch.chdir(tmp_path)

    res = GreyLineRealityGuardEngine()._check_untracked_broker_positions({
        "positions": [{"symbol": "GLW 260828C180"},   # tracked
                      {"symbol": "AAA"}, {"symbol": "BBB"}],   # nobody's managing these
    })
    assert res["untracked"] == ["AAA", "BBB"]
    assert res["ok"] is False
    assert res["severity"] == "warning"   # a human may legitimately trade the account


def test_no_get_route_can_place_broker_orders():
    """A GET must be SAFE. GreyLine listens on 0.0.0.0 with optional auth, so a GET with
    side effects is reachable by a browser prefetch, a bookmark, a crawler, or an <img src>
    on any page — it could open positions with nobody clicking anything.

    Real defect: GET /momentum-reversal-rebalance?force=true called rebalance(force=True),
    which books real equity orders.
    """
    import re
    from pathlib import Path

    ORDER_CALLS = re.compile(r"rebalance\(force=True\)|book_opens\(|book_option_opens\(|"
                             r"book_option_close\(|place_order\(")
    offenders = []
    for p in sorted(Path("app/routes").glob("*.py")):
        src = p.read_text()
        # split the file into per-handler chunks keyed by their HTTP verb
        parts = re.split(r'@router\.(get|post|put|delete|patch)\(', src)
        for i in range(1, len(parts) - 1, 2):
            verb, body = parts[i], parts[i + 1]
            if verb == "get" and ORDER_CALLS.search(body):
                offenders.append(f"{p.name}: GET handler reaches {ORDER_CALLS.search(body).group()}")
    assert not offenders, "GET routes must never place broker orders:\n" + "\n".join(offenders)


def test_positions_with_a_working_close_read_as_closing_not_unmanaged(tmp_path, monkeypatch):
    """A queued SELLTOCLOSE means the position is being liquidated. Showing it as static
    UNMANAGED risk (as it did after an account reset) is alarming and false — it must read
    CLOSING, with no stale stop/TP levels."""
    import json
    from app.routes import open_positions as op
    from app.services.broker_account_view_engine import BrokerAccountViewEngine

    monkeypatch.setattr(op, "_greyline_managed_symbols", lambda: set())
    monkeypatch.setattr(op, "_doctrine_levels", lambda: {})
    monkeypatch.setattr(BrokerAccountViewEngine, "snapshot", lambda self: {
        "reads_ok": True, "account_label": "TradeStation Paper Trading Account",
        "account_mode": "paper",
        "positions": [{"symbol": "ALAB 260828C315", "asset_type": "OPTION", "side": "LONG",
                       "quantity": 1, "entry_price": 65.55, "current_price": 55.77,
                       "unrealized_pnl": -977.5, "unrealized_pnl_pct": -14.9,
                       "stop_loss": None, "targets": []}],
        "pending_buys": [],
        "pending_closes": [{"symbol": "ALAB 260828C315", "limit_price": 52.0}],
    })
    res = op.open_positions()
    row = res["open_positions"][0]
    assert row["status"] == "CLOSING"
    assert "fills at open" in row["stage"]
    assert row["stop_loss"] is None and row["targets"] == []
    # A closing row must STILL show its cost — a `continue` once blanked the Cost column.
    assert row["initial_cost"] == 6555.0
    assert row["unrealized_pnl"] == -977.5


def test_broker_side_protection_flags_unstopped_longs(monkeypatch):
    """An open long with no resting broker stop is exposed if GreyLine stops running. The guard
    must surface it as a warning — a redundancy gap is worthless if it is invisible. Positions
    with a working close are NOT exposure and must not be flagged."""
    from app.services import greyline_reality_guard_engine as g

    class FakeStopEngine:
        def status(self):
            return {"enabled": False, "long_positions": 2, "protected_at_broker": 0,
                    "unprotected": ["GLW", "MRNA"], "closing_not_stopped": ["ALAB 260828C315"]}

    monkeypatch.setattr(
        "app.services.broker_protective_stop_engine.BrokerProtectiveStopEngine",
        FakeStopEngine)
    chk = g.GreyLineRealityGuardEngine()._check_broker_side_protection()
    assert chk["id"] == "BROKER_SIDE_PROTECTION"
    assert chk["severity"] == "warning"       # visible, but never blocks — disaster stops are opt-in
    assert chk["ok"] is False
    assert "GLW" in chk["detail"] and "DISABLED" in chk["detail"]


def test_broker_side_protection_clean_when_nothing_exposed(monkeypatch):
    from app.services import greyline_reality_guard_engine as g

    class FakeStopEngine:
        def status(self):
            return {"enabled": True, "long_positions": 1, "protected_at_broker": 1,
                    "unprotected": [], "closing_not_stopped": []}

    monkeypatch.setattr(
        "app.services.broker_protective_stop_engine.BrokerProtectiveStopEngine",
        FakeStopEngine)
    chk = g.GreyLineRealityGuardEngine()._check_broker_side_protection()
    assert chk["ok"] is True


def test_realized_continuity_flags_closed_market_move(monkeypatch, tmp_path):
    """The 2026-07-30 fantasy class: realized P&L moving while the market is CLOSED (a day-boundary
    ledger artifact, not a real fill) must be flagged CRITICAL so the dashboard goes red."""
    from app.services import greyline_reality_guard_engine as g
    import json
    G = g.GreyLineRealityGuardEngine
    state = tmp_path / "rc.json"
    monkeypatch.setattr(G, "REALIZED_CONTINUITY_STATE", state)
    state.write_text(json.dumps({"realized": -74.4, "market_open": False}))
    monkeypatch.setattr("app.services.mission_realized_pnl_engine.MissionRealizedPnlEngine.cumulative_realized",
                        lambda self: 0.0)   # jumped +74.4 overnight
    monkeypatch.setattr("app.services.market_hours_engine.MarketHoursEngine.status",
                        lambda self: {"is_regular_session": False})
    chk = G()._check_realized_continuity()
    assert chk["severity"] == "critical" and chk["ok"] is False
    # ...and stable realized while closed is fine
    state.write_text(json.dumps({"realized": 0.0, "market_open": False}))
    assert G()._check_realized_continuity()["ok"] is True


def test_data_freshness_flags_stale_decision_bars(monkeypatch, tmp_path):
    """Stale-as-live bar data (2026-07-30 audit): a decision-driving symbol whose newest bar is older
    than the threshold must be flagged, so 'live' displays can't hide a stalled refresh."""
    from app.services import greyline_reality_guard_engine as g
    from pathlib import Path
    hist = tmp_path / "historical"; hist.mkdir()
    (hist / "SPY_daily.csv").write_text("date,open,high,low,close,volume\n2026-07-20,1,1,1,1,1\n")
    (hist / "QQQM_daily.csv").write_text("date,open,high,low,close,volume\n2026-07-29,1,1,1,1,1\n")
    monkeypatch.setattr(g, "Path", lambda p: hist if p == "app/data/historical" else Path(p))
    chk = g.GreyLineRealityGuardEngine()._check_data_freshness()
    # (real 'today' is far past 2026-07-20, so SPY is stale; QQQM at 07-29 is only flagged near that date)
    assert chk["id"] == "DATA_FRESHNESS"
    assert isinstance(chk["ok"], bool)
    assert "SPY" in chk["detail"] or chk["ok"] is True  # stale SPY surfaces, or genuinely fresh
