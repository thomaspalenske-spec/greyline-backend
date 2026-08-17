"""Reality Guard: every OPEN momentum position must be managed to the stop it recorded at entry, so the
edge court's risk denominator is ENFORCED, not just measured. Grace for fresh opens; tolerance for ATR drift."""

from datetime import datetime, timedelta

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


def _iso(hours_ago):
    return (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat()


def _rows(monkeypatch, rows, read_ok=True):
    # _momentum_open_rows now returns (rows, read_ok) so a swallowed ledger read is surfaced, not
    # silently reported as "all managed". Tests pass read_ok=False to exercise the read-failure branch.
    monkeypatch.setattr(G, "_momentum_open_rows", staticmethod(lambda: (rows, read_ok)))


def test_consistent_stops_pass(monkeypatch):
    _rows(monkeypatch, [{"symbol": "GLW", "entry_price": 100.0, "entry_stop": 90.0, "timestamp": _iso(5),
                         "exit_doctrine": {"initial_stop": 90.1}}])   # within 2% tolerance
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is True


def test_managed_stop_mismatch_flags(monkeypatch):
    _rows(monkeypatch, [{"symbol": "GLW", "entry_price": 100.0, "entry_stop": 90.0, "timestamp": _iso(5),
                         "exit_doctrine": {"initial_stop": 85.0}}])   # 5 off = 5% > 2% tolerance
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is False and "GLW" in inv["detail"] and "!=" in inv["detail"]


def test_unmanaged_past_grace_flags(monkeypatch):
    _rows(monkeypatch, [{"symbol": "MRNA", "entry_price": 50.0, "entry_stop": 45.0, "timestamp": _iso(6),
                         }])   # recorded a stop but no doctrine plan, 6h old
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is False and "UNMANAGED" in inv["detail"]


def test_fresh_unmanaged_within_grace_passes(monkeypatch):
    _rows(monkeypatch, [{"symbol": "MRNA", "entry_price": 50.0, "entry_stop": 45.0, "timestamp": _iso(0.2),
                         }])   # opened 12 min ago -> doctrine attaches next cycle, within grace
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is True


def test_pre_feature_row_without_stop_is_skipped(monkeypatch):
    _rows(monkeypatch, [{"symbol": "OLD", "entry_price": 100.0, "timestamp": _iso(48)}])  # no entry_stop
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is True


def test_unreadable_ledger_is_surfaced_not_claimed_managed(monkeypatch):
    # A swallowed ledger read must NOT be reported as "all managed" — the detail says UNVERIFIED so the
    # gap is visible, rather than a falsely-clean "positions managed" pass.
    _rows(monkeypatch, [], read_ok=False)
    inv = G()._check_momentum_stops_consistent()
    assert "UNVERIFIED" in inv["detail"].upper() and "managed to their recorded" not in inv["detail"]


def test_no_recorded_stops_yet_does_not_claim_managed(monkeypatch):
    # Readable ledger, only pre-feature rows (nothing to verify) → passes, but the detail must not claim
    # positions are "managed" when zero were actually checked.
    _rows(monkeypatch, [{"symbol": "OLD", "entry_price": 100.0, "timestamp": _iso(48)}])
    inv = G()._check_momentum_stops_consistent()
    assert inv["ok"] is True and "managed" not in inv["detail"].lower()
