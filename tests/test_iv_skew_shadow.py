"""IV-skew shadow: rank optionable single names by 25d risk reversal, long top-K / short bottom-K, settle as a
market-neutral SPREAD at live equity quotes, judged on the court's bar. Hermetic — skew/prices monkeypatched."""

import json

import pytest

from app.services.iv_skew_shadow_engine import IvSkewShadowEngine as I


@pytest.fixture(autouse=True)
def _session_open(monkeypatch):
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(I, "STATE", tmp_path)
    monkeypatch.setattr(I, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(I, "CLOSED", tmp_path / "c.jsonl")


def test_signal_ranks_by_risk_reversal(monkeypatch):
    uni = ["L%d" % i for i in range(8)] + ["S%d" % i for i in range(8)]
    skew = {**{"L%d" % i: 0.05 - i * 0.001 for i in range(8)},   # highest RR -> long
            **{"S%d" % i: -0.02 - i * 0.001 for i in range(8)}}  # lowest RR (put-skewed) -> short
    monkeypatch.setattr(I, "_universe", lambda self: uni)
    monkeypatch.setattr(I, "_skew_by_symbol", lambda self, syms: skew)
    tg = I()._signal_ls()
    assert {p["symbol"] for p in tg["long"]} == {"L%d" % i for i in range(8)}
    assert {p["symbol"] for p in tg["short"]} == {"S%d" % i for i in range(8)}


def test_signal_none_when_too_few_readings(monkeypatch):
    monkeypatch.setattr(I, "_universe", lambda self: ["A", "B", "C"])
    monkeypatch.setattr(I, "_skew_by_symbol", lambda self, syms: {"A": 0.1, "B": 0.0, "C": -0.1})
    assert I()._signal_ls() is None                      # < 2*TOP_K names


def test_mark_opens_and_settles_market_neutral_spread(tmp_path, monkeypatch):
    monkeypatch.setenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")   # 0.001 round-trip
    _isolate(monkeypatch, tmp_path)
    uni = ["L%d" % i for i in range(8)] + ["S%d" % i for i in range(8)]
    skew = {**{"L%d" % i: 0.05 for i in range(8)}, **{"S%d" % i: -0.05 for i in range(8)}}
    monkeypatch.setattr(I, "_universe", lambda self: uni)
    monkeypatch.setattr(I, "_skew_by_symbol", lambda self, syms: skew)
    monkeypatch.setattr(I, "_live_prices", lambda self, syms: {str(s).upper(): 100.0 for s in syms})

    r1 = I().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    legs = json.loads((tmp_path / "o.json").read_text())[0]["legs"]
    assert sum(1 for l in legs if l["side"] == "BUY") == 8 and sum(1 for l in legs if l["side"] == "SELL") == 8

    o = json.loads((tmp_path / "o.json").read_text())
    o[0]["opened"] = "2020-01-01"                        # age past the weekly hold
    (tmp_path / "o.json").write_text(json.dumps(o))
    # longs +10%, shorts -5% -> spread 0.15
    monkeypatch.setattr(I, "_live_prices",
                        lambda self, syms: {str(s).upper(): (110.0 if str(s).upper().startswith("L") else 95.0)
                                            for s in syms})
    r3 = I().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    assert abs(rec["gross_spread"] - 0.15) < 1e-6
    assert abs(rec["net_return"] - (0.15 - 2 * 0.001)) < 1e-6   # cost on BOTH sleeves
    assert rec["n_long"] == 8 and rec["n_short"] == 8


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_IV_SKEW_SHADOW", "false")
    assert I().mark()["status"] == "IV_SKEW_SHADOW_DISABLED"


def test_report_structure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(I, "_universe", lambda self: [])
    monkeypatch.setattr(I, "_live_prices", lambda self, s: {})
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"net_return": 0.004}) for _ in range(3)) + "\n")
    r = I().report()
    assert r["cohorts_closed"] == 3 and "accumulating" in r["verdict"].lower()
    assert r["rigorous_verdict"]["verdict"].startswith("ACCUMULATING")
