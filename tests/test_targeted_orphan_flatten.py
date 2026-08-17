"""Targeted flatten — close ONLY the named tickers (orphans from a disarmed sleeve), never the rest.

FlattenAllPositionsEngine.run_cycle(only_symbols=[...]) reuses the whole-book flatten's marketable-close
safety but restricted to a subset, so trend/carry positions are untouched. Targeted mode is gated by the
CALLER (the scheduler checks GREYLINE_ORPHAN_FLATTEN), so it works even with the whole-book arm off; the
whole-book mode still requires GREYLINE_FLATTEN_ALL_ENABLED. dry_run keeps it order-free (conftest also
blocks real orders).
"""

import app.services.tradestation_quote_live_engine as qmod
from app.services.flatten_all_positions_engine import FlattenAllPositionsEngine as F

ORPHANS = ["EEM", "EFAV", "SPLV", "USMV", "XMLV"]


def _stub(monkeypatch, held):
    monkeypatch.setattr(qmod.TradeStationQuoteLiveEngine, "get_quote",
                        lambda self, s: {"response_json": {"Quotes": [{"Bid": 10.0, "Ask": 10.02}]}})
    monkeypatch.setattr(F, "_positions", lambda self, book: list(held))
    monkeypatch.setattr(F, "_working_closes", lambda self, book, sym: [])


def test_targeted_flatten_only_touches_named_held_symbols(monkeypatch):
    _stub(monkeypatch, [("EEM", 4), ("USMV", 3), ("QQQM", 8), ("SVXY", 87), ("DBC", 27)])
    r = F().run_cycle(is_regular_session=True, dry_run=True, only_symbols=ORPHANS)
    touched = {a["symbol"] for a in r["actions"]}
    assert touched == {"EEM", "USMV"}                       # only held orphans; trend/carry untouched
    assert all(a["would"] in ("SELL", "SELLTOCLOSE") for a in r["actions"])   # sells-only (de-risking)


def test_targeted_mode_ignores_the_whole_book_arm(monkeypatch):
    monkeypatch.setenv("GREYLINE_FLATTEN_ALL_ENABLED", "false")   # whole-book arm OFF
    _stub(monkeypatch, [("EEM", 4)])
    r = F().run_cycle(is_regular_session=True, dry_run=True, only_symbols=ORPHANS)
    assert r["status"] != "FLATTEN_ALL_DISABLED"
    assert {a["symbol"] for a in r["actions"]} == {"EEM"}


def test_whole_book_mode_still_requires_the_arm(monkeypatch):
    monkeypatch.setenv("GREYLINE_FLATTEN_ALL_ENABLED", "false")
    r = F().run_cycle(is_regular_session=True, dry_run=True)      # no only_symbols
    assert r["status"] == "FLATTEN_ALL_DISABLED"


def test_targeted_is_flat_when_named_symbols_not_held(monkeypatch):
    _stub(monkeypatch, [("QQQM", 8), ("DBC", 27)])               # no orphans held
    r = F().run_cycle(is_regular_session=True, dry_run=True, only_symbols=ORPHANS)
    assert r["status"] == "FLATTEN_ALL_FLAT" and r["actions"] == []


def test_targeted_market_closed_is_a_cheap_noop(monkeypatch):
    # closed session must short-circuit BEFORE any broker read (no hammering after hours)
    called = {"pos": 0}
    monkeypatch.setattr(F, "_positions", lambda self, book: called.__setitem__("pos", called["pos"] + 1) or [])
    r = F().run_cycle(is_regular_session=False, dry_run=True, only_symbols=ORPHANS)
    assert r["status"] == "FLATTEN_ALL_MARKET_CLOSED" and called["pos"] == 0
