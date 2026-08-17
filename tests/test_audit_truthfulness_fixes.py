"""Regression tests for the consolidated full-audit truthfulness fixes.

Each locks in a "degraded/failed state must not read as healthy" invariant surfaced by the audit.
No network — every external read is monkeypatched.
"""

import json
from pathlib import Path

import pytest


# ---- M4: broker reads_ok requires a parseable Balances body, not just HTTP 200 -------------------

def test_reads_ok_false_on_empty_balances_despite_200(monkeypatch):
    import app.services.broker_account_view_engine as bav

    def _200(_self):
        return {"http_status": 200, "response_json": {}}   # 200 but no Balances (auth interstitial)

    monkeypatch.setattr(bav.TradeStationBalanceLiveEngine, "get_balance", _200, raising=False)
    monkeypatch.setattr(bav.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: {"http_status": 200, "response_json": {"Positions": []}}, raising=False)
    monkeypatch.setattr(bav.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"http_status": 200, "response_json": {"Orders": []}}, raising=False)
    # resolve a source so snapshot proceeds to the reads
    monkeypatch.setattr(bav.TradeStationAccountSourceEngine, "resolve",
                        lambda self: {"ok": True, "mode": "paper", "label": "TS Paper"}, raising=False)

    snap = bav.BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is False   # empty/200 must NOT read as a healthy all-cash book


def test_reads_ok_true_when_balances_present(monkeypatch):
    import app.services.broker_account_view_engine as bav

    monkeypatch.setattr(bav.TradeStationBalanceLiveEngine, "get_balance",
                        lambda self: {"http_status": 200,
                                      "response_json": {"Balances": [{"CashBalance": "10000"}]}}, raising=False)
    monkeypatch.setattr(bav.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: {"http_status": 200, "response_json": {"Positions": []}}, raising=False)
    monkeypatch.setattr(bav.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"http_status": 200, "response_json": {"Orders": []}}, raising=False)
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "_account_id", lambda self: "SIM_TEST", raising=False)

    snap = bav.BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is True


# ---- A1: condor-shadow surfaces a thrown sleeve instead of silently dropping it ------------------

def test_condor_shadow_report_surfaces_sleeve_errors(tmp_path, monkeypatch):
    import app.services.condor_shadow_engine as cse
    monkeypatch.setattr(cse, "STATE", tmp_path)
    monkeypatch.setattr(cse, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(cse.CondorShadowEngine, "ERRORS", tmp_path / "sleeve_errors.json")

    eng = cse.CondorShadowEngine()
    eng._write_sleeve_errors({"vrp": "boom"})
    rep = eng.report()
    assert rep["degraded"] is True
    assert rep["sleeve_errors"] == {"vrp": "boom"}
    assert rep["status"] == "CONDOR_SHADOW_DEGRADED"


def test_condor_shadow_report_clean_when_no_errors(tmp_path, monkeypatch):
    import app.services.condor_shadow_engine as cse
    monkeypatch.setattr(cse, "STATE", tmp_path)
    monkeypatch.setattr(cse, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(cse.CondorShadowEngine, "ERRORS", tmp_path / "sleeve_errors.json")

    rep = cse.CondorShadowEngine().report()
    assert rep["degraded"] is False
    assert rep["status"] != "CONDOR_SHADOW_DEGRADED"


# ---- A3: a failed close-of-day read goes out as DEGRADED, never a calm INFO with $None ------------

def test_post_close_report_degrades_on_governor_failure(monkeypatch):
    import app.services.scheduled_operator_reports_engine as sr

    sent = {}

    def _capture(title, message, severity, fingerprint):
        sent.update(title=title, message=message, severity=severity)
        return {"sent": True}

    monkeypatch.setattr(sr.ScheduledOperatorReportsEngine, "_dispatch", staticmethod(_capture))

    # governor read fails
    import app.services.mission_risk_governor_engine as mrg
    monkeypatch.setattr(mrg.MissionRiskGovernorEngine, "snapshot",
                        lambda self: (_ for _ in ()).throw(RuntimeError("broker down")))

    sr.ScheduledOperatorReportsEngine._post_close_report("2026-07-31")
    assert sent["severity"] == "WARNING"
    assert "DEGRADED" in sent["title"]
    assert "$None" not in sent["message"]   # the exact fantasy this fix prevents
