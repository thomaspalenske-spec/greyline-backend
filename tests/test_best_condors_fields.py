"""The Iron Condor list: DTE is computed (not a missing key), and a throwing sleeve is SURFACED,
never silently dropped. No network.
"""

from datetime import date, timedelta

from app.services.best_condors_engine import BestCondorsEngine


def test_fmt_computes_dte_from_expiration():
    exp = (date.today() + timedelta(days=30)).isoformat()
    row = BestCondorsEngine()._fmt({"symbol": "X", "expiration": exp, "legs": {}}, "VRP")
    assert row["dte"] == 30                          # was always None (read a non-existent entry_dte key)
    assert row["expiration"] == exp


def test_fmt_dte_none_when_no_expiration():
    row = BestCondorsEngine()._fmt({"symbol": "X", "legs": {}}, "VRP")
    assert row["dte"] is None                        # graceful, not a crash


def test_gather_surfaces_a_throwing_sleeve(monkeypatch):
    import app.services.conditional_vrp_short_premium_engine as vrp_mod
    import app.services.earnings_vol_harvest_engine as earn_mod

    def _boom(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(vrp_mod.ConditionalVRPShortPremiumEngine, "plan", _boom)
    monkeypatch.setattr(earn_mod.EarningsVolHarvestEngine, "open_positions",
                        lambda self, dry_run=True: {"planned": []})
    rows, errors = BestCondorsEngine()._gather()
    assert "VRP" in errors and "boom" in errors["VRP"]   # surfaced, not swallowed
    assert isinstance(rows, list)
