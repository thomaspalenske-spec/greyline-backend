"""END-TO-END trade-readiness audit — "can GreyLine actually fire an order when the market opens?"

This walks the WHOLE open chain against LIVE state (real .env, real broker reads, real decision caches):

    scheduler cycle  →  broker token + account resolve + balances/positions/orders read
    →  execution authority (the real gate: paper-exec + SIM-booking coherent)
    →  SIM fail-closed guard  →  order-body verification (reject ≠ filled)
    →  each of the 6 sleeves' decision surface  →  capital / exposure / risk gates
    →  data freshness  →  Reality Guard (no fantasy)

It NEVER places an order: every check is read-only, the order-path check uses synthetic payloads, and
conftest hard-blocks place_order as a backstop. It is EXEMPT from the data sandbox (see conftest
_EXEMPT_MODULES) so it reads the real app/data and hits the real broker — that is the point of an
end-to-end audit. Run it directly to get a GO/NO-GO board:

    python3 -m pytest tests/test_end_to_end_trade_readiness.py -s

Two tests:
  * test_trade_firing_machinery_is_correct — DETERMINISTIC. The audit + safety machinery is wired
    correctly regardless of live market state (stable regression guard).
  * test_live_trade_readiness_go — the LIVE audit verdict. Asserts the trade-firing SPINE is GO and
    prints the full board; if the system genuinely cannot trade, it FAILS naming the broken link
    (state-dependent BY DESIGN — that is what makes it an audit).
"""

import base64
import json
import os
import urllib.request

import pytest

from app.services.pre_open_readiness_engine import PreOpenReadinessEngine

# The links that MUST be healthy for a decided order to actually book at the bell. A FAIL in any of
# these is a NO-GO. (Market-hours-dependent or config checks — carry_signal_data, capital_params,
# strategy_flags — are reported but not part of this hard spine.)
SPINE_CRITICAL = (
    "execution_authority",       # paper execution armed AND SIM booking on (the real gate)
    "broker_connectivity",       # token read + account resolves + balances/positions/orders read
    "sim_booking_target_safe",   # booking structurally targets the SIM sandbox (live fail-closed)
    "order_path_integrity",      # order success verified from the BODY, not HTTP 200
    "reality_guard",             # no critical fantasy invariant tripped
)

# Every check the extended audit must emit — a structural regression guard against a silently dropped link.
EXPECTED_CHECKS = {
    "reset_armed", "strategy_flags_pre_open", "capital_params", "trend_data_fresh", "carry_signal_data",
    "momentum_path", "vrp_path", "earnings_path", "carry_path", "trend_path", "tbill_path",
    "reality_guard", "mission_accounting",
    "execution_authority", "broker_connectivity", "sim_booking_target_safe", "order_path_integrity",
    "scheduler_liveness", "exposure_gate",
}


def _audit():
    return PreOpenReadinessEngine().audit()


def _by_name(report):
    return {c["check"]: c for c in report["checks"]}


def _live_scheduler_status():
    """Best-effort: ask the RUNNING service for the real scheduler thread state (thread_alive is
    process-local, so the in-process audit can't see the trading thread). Never fails the test."""
    try:
        pw = os.getenv("GREYLINE_DASHBOARD_PASSWORD", "")
        req = urllib.request.Request("http://127.0.0.1:8000/background-scheduler/status")
        if pw:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"audit:{pw}".encode()).decode())
        with urllib.request.urlopen(req, timeout=5) as r:   # noqa: S310 (localhost only)
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_unreachable": repr(e)[:100]}


def _print_board(report, sched):
    checks = _by_name(report)
    spine_fail = [n for n in SPINE_CRITICAL if checks.get(n, {}).get("status") == "FAIL"]
    verdict = "NO-GO" if spine_fail else "GO"
    line = "=" * 92
    print("\n" + line)
    print(f" GREYLINE END-TO-END TRADE READINESS  —  SPINE: {verdict}"
          f"   (engine overall: {report['overall']}, {report['fail_count']} fail / {report['warn_count']} warn)")
    print(line)
    for c in report["checks"]:
        star = " *" if c["check"] in SPINE_CRITICAL else "  "
        print(f"{star}[{c['status']:4}] {c['check']:24} {c['detail']}")
    # the live-service scheduler truth (process-local thread_alive can't be seen from this process)
    if "_unreachable" in sched:
        print(f"  [ -- ] live_scheduler          service not reached ({sched['_unreachable']}) — "
              f"check GET /background-scheduler/status manually")
    else:
        print(f"  [{'PASS' if sched.get('thread_alive') else 'WARN'}] live_scheduler          "
              f"thread_alive={sched.get('thread_alive')}, last={sched.get('last_status')}, "
              f"consecutive_failures={sched.get('consecutive_failures')}, "
              f"success_rate={sched.get('cycle_success_rate_pct')}%")
    print(line + "\n")
    return spine_fail


# --------------------------------------------------------------------------------------------------

def test_trade_firing_machinery_is_correct():
    """DETERMINISTIC: the audit emits every link, nothing throws, and the two SAFETY guards
    (order-body verification + SIM fail-closed) behave correctly. Stable regardless of market state."""
    report = _audit()
    checks = _by_name(report)

    # every expected link is present — no silently dropped check
    missing = EXPECTED_CHECKS - set(checks)
    assert not missing, f"audit dropped checks: {sorted(missing)}"

    # no check produced an empty/None status (i.e. none silently failed to run)
    for c in report["checks"]:
        assert c["status"] in ("PASS", "WARN", "FAIL"), f"bad status on {c['check']}: {c}"

    # SAFETY GUARD 1 — the order-body verifier rejects a body-level reject even on HTTP 200. This is a
    # direct call to the same function the audit uses, so a broken guard fails here deterministically.
    from app.services.tradestation_sim_booking_engine import _interpret_order
    assert _interpret_order(200, {"Orders": [{"OrderID": "999"}]})[0] is True
    assert _interpret_order(200, {"Orders": [{"OrderID": "0", "Error": "reject"}]})[0] is False
    assert _interpret_order(200, {"Errors": [{"m": "x"}]})[0] is False
    assert _interpret_order(500, {})[0] is False
    assert checks["order_path_integrity"]["status"] == "PASS", checks["order_path_integrity"]["detail"]

    # SAFETY GUARD 2 — booking is structurally locked to the SIM sandbox account (live fail-closed).
    assert checks["sim_booking_target_safe"]["status"] == "PASS", checks["sim_booking_target_safe"]["detail"]


def test_live_trade_readiness_go():
    """LIVE AUDIT: assert the trade-firing spine is GO and print the full board. State-dependent by
    design — a genuine NO-GO fails the test and names the broken link."""
    report = _audit()
    checks = _by_name(report)
    sched = _live_scheduler_status()
    spine_fail = _print_board(report, sched)

    # If the broker is entirely UNCONFIGURED (no token at all), this is infra-absence, not a trading
    # signal — skip rather than red. A configured-but-failing link still asserts below.
    from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine
    tok = TradeStationTokenStatusEngine().evaluate()
    if not tok.get("access_token_present") and not tok.get("refresh_token_present"):
        pytest.skip("no TradeStation token configured — cannot audit live broker connectivity")

    # THE GATE: no critical spine link may be FAIL.
    assert not spine_fail, (
        "GreyLine is NOT ready to trade at open — broken spine link(s): "
        + "; ".join(f"{n}: {checks[n]['detail']}" for n in spine_fail))

    # The core question: is execution actually armed to book at the bell?
    assert checks["execution_authority"]["status"] == "PASS", checks["execution_authority"]["detail"]

    # Something must be armed to open, or nothing fires regardless of the rest.
    assert checks["strategy_flags_pre_open"]["status"] == "PASS", (
        "no sleeves armed — nothing will open: " + checks["strategy_flags_pre_open"]["detail"])
