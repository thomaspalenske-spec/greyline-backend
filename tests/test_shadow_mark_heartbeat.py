"""Shadow-mark heartbeat + reality-guard silent-stall surfacing (2026-08-17 freeze class).

The heartbeat's `last_ran` advances ONLY when a shadow actually executed (not deferred/disabled/errored), so a
multi-day gap is an unambiguous silent stall regardless of a shadow's cohort cadence. The reality-guard check
then turns that gap into a LOUD banner line — but with the cry-wolf discipline: enabled-only, scheduler-live-only,
missing-heartbeat baselines silently."""

import time

import pytest

import app.services.shadow_mark_heartbeat as HB


@pytest.fixture(autouse=True)
def _tmp_hb(monkeypatch, tmp_path):
    monkeypatch.setattr(HB, "HEARTBEAT_FILE", tmp_path / "heartbeats.json")
    yield


def test_ran_classifier_distinguishes_ran_from_not_ran():
    assert HB._ran({"status": "GEX_SHADOW_MARKED", "acted": True}) is True
    assert HB._ran({"status": "CONDOR_SHADOW_DONE"}) is True
    assert HB._ran({"status": "GEX_SHADOW_DEFERRED_OPEN_WINDOW"}) is False
    assert HB._ran({"status": "IV_SKEW_SHADOW_DISABLED"}) is False
    assert HB._ran({"status": "DISPERSION_SHADOW_DEGRADED"}) is False
    assert HB._ran({"error": "boom", "status": "X"}) is False
    assert HB._ran("not a dict") is False
    assert HB._ran(None) is False


def test_record_advances_last_ran_only_when_ran():
    HB.record({
        "gex_strategy": {"status": "GEX_SHADOW_MARKED"},
        "condor": {"status": "CONDOR_SHADOW_DEFERRED_OPEN_WINDOW"},
    })
    hb = HB.read()
    assert "last_ran" in hb["gex_strategy"]
    # deferred shadow was SEEN this cycle but never actually ran -> no last_ran stamp
    assert "last_ran" not in hb["condor"]
    assert "last_seen" in hb["condor"]
    assert "DEFERRED" in hb["condor"]["last_status"]


def test_record_does_not_regress_last_ran_on_a_later_deferral():
    HB.record({"gex_strategy": {"status": "GEX_SHADOW_MARKED"}})
    first = HB.read()["gex_strategy"]["last_ran"]
    # a subsequent cycle where the same shadow is deferred must NOT wipe/refresh last_ran
    HB.record({"gex_strategy": {"status": "GEX_SHADOW_DEFERRED_OPEN_WINDOW"}})
    assert HB.read()["gex_strategy"]["last_ran"] == first


def test_reality_guard_flags_stale_enabled_shadow(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    from app.services.background_scheduler_service import BackgroundSchedulerService as S

    monkeypatch.setattr(S, "scheduler_live", classmethod(lambda cls: True))
    # a stale heartbeat: gex last ran 9 days ago
    HB.record({"gex_strategy": {"status": "GEX_SHADOW_MARKED"}})
    state = HB.read()
    state["gex_strategy"]["last_ran"] = time.time() - 9 * 86400
    HB.HEARTBEAT_FILE.write_text(__import__("json").dumps(state))
    # force the gex engine to report enabled
    from app.services.gex_mean_reversion_shadow_engine import GexMeanReversionShadowEngine as GX
    monkeypatch.setattr(GX, "enabled", staticmethod(lambda: True))

    r = G()._check_shadow_freshness()
    assert r["ok"] is False
    assert "gex_strategy" in r["detail"]


def test_reality_guard_quiet_when_fresh(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    from app.services.background_scheduler_service import BackgroundSchedulerService as S
    monkeypatch.setattr(S, "scheduler_live", classmethod(lambda cls: True))
    HB.record({"gex_strategy": {"status": "GEX_SHADOW_MARKED"}})   # just now
    r = G()._check_shadow_freshness()
    assert r["ok"] is True


def test_reality_guard_baselines_silently_when_no_heartbeat(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    from app.services.background_scheduler_service import BackgroundSchedulerService as S
    monkeypatch.setattr(S, "scheduler_live", classmethod(lambda cls: True))
    # empty heartbeat file -> nothing to flag
    r = G()._check_shadow_freshness()
    assert r["ok"] is True


def test_reality_guard_quiet_when_scheduler_down(monkeypatch):
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    from app.services.background_scheduler_service import BackgroundSchedulerService as S
    monkeypatch.setattr(S, "scheduler_live", classmethod(lambda cls: False))
    # even a wildly stale heartbeat must stay quiet — the scheduler-down alarm owns it
    HB.record({"gex_strategy": {"status": "GEX_SHADOW_MARKED"}})
    state = HB.read()
    state["gex_strategy"]["last_ran"] = time.time() - 30 * 86400
    HB.HEARTBEAT_FILE.write_text(__import__("json").dumps(state))
    r = G()._check_shadow_freshness()
    assert r["ok"] is True
