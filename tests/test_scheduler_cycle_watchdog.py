"""Cycle-duration watchdog: off-box alert when a scheduler cycle runs pathologically long (it can straddle
the market open and misfire). Fires on the cycle wall-clock OR any single phase crossing its threshold,
names the dominant phase, deduped by (dominant + duration bucket). Thresholds default ABOVE the normal
7-14min band so a healthy cycle never pages. Best-effort — a timing alert never breaks the cycle."""

import app.services.background_scheduler_service as mod
from app.services.background_scheduler_service import BackgroundSchedulerService as S


class _Alert:
    def __init__(self, sink):
        self._sink = sink

    def has_external_channel(self):
        return True

    def dispatch(self, title, message, severity, fingerprint):
        self._sink.append({"title": title, "message": message, "severity": severity, "fingerprint": fingerprint})


def _capture(monkeypatch, timings, env=None):
    sink = []
    monkeypatch.setattr(S, "_last_phase_timings", dict(timings))
    import app.services.external_alert_engine as ae
    monkeypatch.setattr(ae, "ExternalAlertEngine", lambda: _Alert(sink))
    monkeypatch.setattr(mod, "getenv", lambda k, d="": (env or {}).get(k, d))
    return sink


def test_healthy_cycle_does_not_page(monkeypatch):
    # 10-min cycle is within the normal band (< 20-min default) and no phase > 10min -> silent
    sink = _capture(monkeypatch, {"vrp_short_premium": 120.0, "_total_instrumented": 200.0})
    S._watch_cycle_duration(600_000)                   # 600s
    assert sink == []


def test_pathologically_long_cycle_pages_with_dominant_phase(monkeypatch):
    sink = _capture(monkeypatch, {"pre_sleeve": 30.0, "vrp_short_premium": 1500.0, "_total_instrumented": 1600.0})
    S._watch_cycle_duration(1_900_000)                 # 1900s = ~32min > 1200s default
    assert len(sink) == 1
    a = sink[0]
    assert a["severity"] == "WARNING" and "vrp_short_premium" in a["message"]
    assert a["fingerprint"].startswith("SCHED_CYCLE_SLOW:vrp_short_premium")


def test_single_hot_phase_pages_even_if_cycle_under_threshold(monkeypatch):
    # cycle 700s (< 1200 cycle threshold) but earnings phase 650s (> 600 phase threshold) -> page
    sink = _capture(monkeypatch, {"earnings_vol": 650.0, "_total_instrumented": 680.0})
    S._watch_cycle_duration(700_000)
    assert len(sink) == 1 and "earnings_vol" in sink[0]["message"]


def test_dedup_bucket_changes_on_worsening(monkeypatch):
    t = {"vrp_short_premium": 1500.0, "_total_instrumented": 1600.0}
    sink = _capture(monkeypatch, t)
    S._watch_cycle_duration(1_300_000)                 # ~21.7min -> bucket 10
    S._watch_cycle_duration(1_900_000)                 # ~31.7min -> bucket 15 (worsened) -> different fp
    fps = {a["fingerprint"] for a in sink}
    assert len(fps) == 2                               # two distinct buckets -> re-pages on worsening


def test_env_threshold_override(monkeypatch):
    # lower the cycle threshold to 300s -> a 600s cycle now pages
    sink = _capture(monkeypatch, {"pre_sleeve": 500.0, "_total_instrumented": 550.0},
                    env={"GREYLINE_CYCLE_SLOW_SECONDS": "300"})
    S._watch_cycle_duration(600_000)
    assert len(sink) == 1


def test_none_duration_is_noop(monkeypatch):
    sink = _capture(monkeypatch, {"vrp_short_premium": 1500.0})
    S._watch_cycle_duration(None)                      # unknown duration -> never pages
    assert sink == []


def test_watchdog_never_raises(monkeypatch):
    # a broken alert engine must NOT be able to break the cycle-record path
    import app.services.external_alert_engine as ae
    monkeypatch.setattr(ae, "ExternalAlertEngine", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(S, "_last_phase_timings", {"vrp_short_premium": 1500.0})
    monkeypatch.setattr(mod, "getenv", lambda k, d="": d)
    S._watch_cycle_duration(1_900_000)                 # must swallow the error
