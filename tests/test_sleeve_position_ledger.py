"""Per-sleeve position ledger — lets overlapping sleeves size against their OWN shares. Gated: disarmed
returns the broker total (byte-identical to legacy); armed returns the sleeve's own position."""

from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine as L


def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "STATE", tmp_path / "sleeve_positions.json")


def test_record_accumulates_signed_and_prunes_zero(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    L.record("trend", "QQQM", 5)          # buy 5
    L.record("trend", "QQQM", -2)         # sell 2
    assert L.position("trend", "QQQM") == 3
    L.record("trend", "QQQM", -3)         # flat -> pruned
    assert L.position("trend", "QQQM") == 0
    assert "trend" not in L._load()       # empty book pruned


def test_effective_held_disarmed_returns_broker(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    monkeypatch.delenv("GREYLINE_PER_SLEEVE_SIZING", raising=False)
    L.record("trend", "QQQM", 5)          # sleeve owns 5...
    # ...but disarmed, the sleeve must size against the BROKER total (legacy behaviour, byte-identical)
    assert L.effective_held("trend", "QQQM", 8) == 8


def _mock_others(monkeypatch, held_by_others):
    """Stub the CONFIRMED other-sleeve holds that effective_held subtracts. The drift-immune design
    (2026-08-06) reads these from SleeveTradeLedgerEngine.held_qty_excluding(exclude, symbol) — the fresh
    broker total minus what OTHER sleeves confirmed-hold — NOT this sleeve's own record()."""
    import app.services.sleeve_trade_ledger_engine as stl
    monkeypatch.setattr(stl.SleeveTradeLedgerEngine, "held_qty_excluding",
                        lambda self, exclude, sym, rows=None: held_by_others.get(exclude, 0))


def test_effective_held_armed_returns_own_not_broker(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    # broker holds 8 QQQM but 3 are xs_momentum's (confirmed) -> trend sizes against its OWN 5, not 8
    _mock_others(monkeypatch, {"trend": 3})
    assert L.effective_held("trend", "QQQM", 8) == 5          # 8 broker - 3 held by other sleeves
    assert L.effective_held("xs_momentum", "QQQM", 8) == 8    # no OTHER sleeve holds it -> full broker total


def test_overlapping_sleeves_do_not_collide(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    # broker holds 8 QQQM = trend 5 + xs_momentum 3 (confirmed); each sizes against its OWN share so neither
    # would liquidate the other's shares
    _mock_others(monkeypatch, {"trend": 3, "xs_momentum": 5})
    assert L.effective_held("trend", "QQQM", 8) == 5
    assert L.effective_held("xs_momentum", "QQQM", 8) == 3


def test_reconcile_total_surfaces_drift(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    L.record("trend", "QQQM", 5)
    L.record("xs_momentum", "QQQM", 3)
    assert L.reconcile_total({"QQQM": 8})["in_sync"] is True         # ledger sum == broker
    r = L.reconcile_total({"QQQM": 6})                               # broker short of the ledger -> drift
    assert r["in_sync"] is False and r["drift"]["QQQM"] == {"ledger": 8, "broker": 6}


def test_seed_attributes_existing_holdings(monkeypatch, tmp_path):
    _iso(monkeypatch, tmp_path)
    L.seed("trend", {"QQQM": 6, "IWM": 3})
    assert L.position("trend", "QQQM") == 6 and L.position("trend", "IWM") == 3
