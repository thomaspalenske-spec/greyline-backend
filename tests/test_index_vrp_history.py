"""Index VRP over the long history (VIX vs forward realized SPY vol). Structural checks are hermetic;
the two headline findings are locked against the real on-disk VIX + SPY series (read-only)."""

import math
from pathlib import Path

import pytest

from app.services.index_vrp_history_research_engine import IndexVRPHistoryResearchEngine as E

_ROOT = Path(__file__).resolve().parents[1]
_REAL_VIX = _ROOT / "app" / "data" / "research" / "vol_term_structure" / "VIX.csv"
_REAL_SPY = _ROOT / "app" / "data" / "historical" / "SPY_daily.csv"


def _write(p, rows):
    p.write_text("date,open,high,low,close\n" + "\n".join(f"{d},0,0,0,{c}" for d, c in rows) + "\n")


def test_forward_window_no_lookahead(tmp_path, monkeypatch):
    # a date can only become an entry once its FORWARD realized window has completed. Need >=20 trailing
    # obs for a causal rank (hardcoded floor in the reused helper), so provide 40 days.
    days = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(40)]
    monkeypatch.setattr(E, "VIX", tmp_path / "vix.csv")
    monkeypatch.setattr(E, "SPY", tmp_path / "spy.csv")
    _write(E.VIX, [(d, 20.0 + (i % 5)) for i, d in enumerate(days)])
    _write(E.SPY, [(d, 100.0 + i) for i, d in enumerate(days)])
    monkeypatch.setattr(E, "RV_WINDOW", 5)
    ent = E()._entries()
    # the last RV_WINDOW dates have no completed forward window -> excluded
    assert ent, "should produce entries"
    assert max(e["date"] for e in ent) <= days[-E.RV_WINDOW - 1]


def test_monthly_cohort_collapse_and_min_days(monkeypatch):
    monkeypatch.setattr(E, "MIN_DAYS_PER_MONTH", 3)
    e = E()
    entries = [{"month": "2020-01", "iv": 0.20, "rv": 0.16} for _ in range(4)] + \
              [{"month": "2020-02", "iv": 0.20, "rv": 0.16} for _ in range(2)]   # Feb below min-days
    m = e._monthly(entries, "volpts")
    assert [mo for mo, _ in m] == ["2020-01"]                        # Feb dropped (2 < 3 days)
    assert abs(m[0][1] - 4.0) < 1e-6                                 # (0.20-0.16)*100 = 4.0 vol pts


def test_edge_bps_and_helpers_are_reused():
    # the engine reuses ConditionalVRP's inference helpers (imported as C in the module), not re-implements
    import app.services.index_vrp_history_research_engine as mod
    from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine as C
    assert mod.C is C                                                # same class, genuine reuse
    assert C._edge_bps(0.20, 0.16) == pytest.approx(0.5 * 0.04 / 0.20 * 10000)


@pytest.mark.skipif(not (_REAL_VIX.exists() and _REAL_SPY.exists()), reason="real VIX/SPY history absent")
def test_real_history_confirms_edge_and_falsifies_rich_iv(monkeypatch):
    monkeypatch.setattr(E, "VIX", _REAL_VIX)
    monkeypatch.setattr(E, "SPY", _REAL_SPY)
    r = E().run(save=False)
    assert r["span"][0] <= "2003-01-01" and r["entry_days"] > 5000    # decades of data, not one year

    unc = r["unconditional"]
    assert unc["status"] == "ANALYZED" and unc["months"] > 200
    # FINDING 1: the unconditional index VRP is a real, significant, net-positive edge
    assert unc["significant_after_family_wise"] is True
    assert unc["net_edge_at_realistic_cost_bps"] > 0
    assert unc["gross_vrp_vol_points"] > 2.0                          # a few vol points, per the literature
    # crash regime is IN the sample and IS the tail — the whole point of the long history
    assert unc["tail"]["worst_month"]["month"].startswith("2020")
    assert unc["tail"]["skew_monthly"] < -1.0                        # heavy left tail

    # FINDING 2: conditioning on rich IV does NOT lift the index edge (it hurts) — the 1yr single-name
    # "~10x lift" was a no-crash-year artifact
    assert r["rich_iv_tercile"]["conditioning_lift_bps"] < 0
    assert r["rich_iv_decile"]["conditioning_lift_bps"] < 0
