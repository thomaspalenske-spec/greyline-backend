"""
Test isolation: run each test in a sandbox CWD that mirrors the repo via symlinks but
gives `app/data/` a FRESH, isolated directory — so unit tests never read or write the
real application data (which previously corrupted the live ledgers and could interfere
with a running server).

Engines persist to relative paths like `Path("app/data/paper_trading/...jsonl")`, which
resolve against CWD at I/O time. Changing CWD to the sandbox redirects those writes;
everything else (source, config) resolves through symlinks to the real repo.

A small allowlist of modules is EXEMPT — they audit the real repo (git/.env) or drive
live routes, need the real working directory, and do not write unit-test data.
"""
import os
from pathlib import Path

import pytest

_SKIP = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}

_EXEMPT_MODULES = {
    "test_credential_security_audit",  # shells out to git in the real repo
    "test_route_audit",                # drives every live route (needs real env)
    "test_schema_audit",               # drives every live route (needs real env)
    "test_end_to_end_trade_readiness", # audits the LIVE trade-firing chain (real data + broker reads)
}


@pytest.fixture(scope="session")
def _data_sandbox(tmp_path_factory):
    real_root = Path(__file__).resolve().parents[1]  # greyline-backend/
    sandbox = tmp_path_factory.mktemp("greyline_sandbox")

    for entry in real_root.iterdir():
        if entry.name in _SKIP:
            continue
        if entry.name == "app":
            (sandbox / "app").mkdir()
            for sub in entry.iterdir():
                dest = sandbox / "app" / sub.name
                if sub.name == "data":
                    dest.mkdir(parents=True, exist_ok=True)  # fresh, isolated
                else:
                    dest.symlink_to(sub)
        else:
            (sandbox / entry.name).symlink_to(entry)

    return sandbox


@pytest.fixture(autouse=True)
def _block_real_broker_orders(monkeypatch):
    """NO test may place a real broker order. Ever.

    The CWD sandbox above isolates FILES, not the network. A test that drives an engine
    end-to-end still reached TradeStation: `test_rebalance_opens_into_free_slots_only`
    monkeypatches the universe to fake symbols AAA/BBB and calls rebalance(force=True),
    whose booking step is unmocked. That was harmless while SIM booking was off — the
    moment GREYLINE_SIM_BOOKING_ENABLED went true, every full test run bought 50 shares
    each of AAA and BBB in the real Paper Trading Account (four fills before this landed).

    So the block lives here, once, for the whole suite: a test that reaches an order
    endpoint FAILS LOUDLY instead of silently trading. Tests that legitimately exercise
    booking logic must mock the booking engine themselves.
    """
    def _forbidden(*_a, **_k):
        raise AssertionError(
            "TEST TRIED TO PLACE A REAL BROKER ORDER. Mock the booking engine "
            "(GreyLineSimExecutionEngine / TradeStationSimBookingEngine) in this test.")

    from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
    monkeypatch.setattr(TradeStationSimBookingEngine, "place_order", _forbidden)
    monkeypatch.setattr(TradeStationSimBookingEngine, "cancel_order", _forbidden)
    # The LIVE client is blocked at the NETWORK layer, not at submit_order(): its whole job
    # is to raise LiveOrderSafetyError BEFORE any POST, and test_live_order_interlock exists
    # to prove exactly that — patching the method would destroy the behaviour under test
    # while still looking green.
    #
    # But `_live.requests` IS the shared requests module, so a blanket patch of .post is
    # global: it broke token refresh, which POSTs to an auth endpoint and has nothing to do
    # with orders. Block on the URL instead — order-execution endpoints raise, everything
    # else calls through untouched.
    try:
        from app.services import greyline_live_broker_client_engine as _live

        _real_post = _live.requests.post

        def _guarded_post(url, *a, **k):
            if "orderexecution" in str(url).lower():
                _forbidden()
            return _real_post(url, *a, **k)

        monkeypatch.setattr(_live.requests, "post", _guarded_post)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _neutralize_external_alerts(monkeypatch):
    """No test may fire a real external alert or pop a macOS notification.

    Recording a CRITICAL operator notification auto-escalates through ExternalAlertEngine —
    which, left unmocked, would POST to a configured webhook/ntfy topic and spawn osascript
    desktop notifications during every suite run. Channels default off in CI, but an operator
    with GREYLINE_ALERT_* set in their shell would get paged by their own test run. Force the
    engine dormant for tests; the alert logic is exercised explicitly in test_external_alert.py
    with its own controlled env.
    """
    for k in ("GREYLINE_ALERT_WEBHOOK_URL", "GREYLINE_ALERT_NTFY_TOPIC",
              "GREYLINE_ALERT_IMESSAGE_TO",
              # operator arming flags for real-order-placing features must never leak into tests
              "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_BROKER_PROTECTIVE_STOPS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GREYLINE_ALERT_MACOS_LOCAL", "false")

    # No test may spawn a LIVE streaming daemon. The app's startup event calls
    # BackgroundSchedulerService.start(), so any test that drives a TestClient (route/schema audits)
    # fires it — and with GREYLINE_TS_*_STREAM_ENABLED='true' in the operator's .env, start_if_enabled()
    # opens a real TS socket in a background thread that then leaks across the session (it was breaking
    # test_ts_quote_stream::test_disabled_does_not_start, which sees the class-level _thread still alive).
    # Force both stream engines dormant. enabled() is patched (not just the env var) because start_if_enabled
    # calls reload_env() first, which would reload the 'true' from .env and clobber a mere setenv (the
    # .env-precedence trap). The engines' own logic is still exercised — the disabled-path unit tests set
    # their flag false and expect DISABLED, which this preserves; no test needs the live-thread path.
    from app.services.tradestation_quote_stream_engine import TradeStationQuoteStreamEngine
    from app.services.tradestation_broker_stream_engine import TradeStationBrokerStreamEngine
    from app.services.uw_stream_engine import UWStreamEngine
    monkeypatch.setenv("GREYLINE_TS_QUOTE_STREAM_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_TS_BROKER_STREAM_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_UW_STREAM_ENABLED", "false")
    monkeypatch.setattr(TradeStationQuoteStreamEngine, "enabled", classmethod(lambda cls: False))
    monkeypatch.setattr(TradeStationBrokerStreamEngine, "enabled", classmethod(lambda cls: False))
    monkeypatch.setattr(UWStreamEngine, "enabled", classmethod(lambda cls: False))   # UW WS: same guard


@pytest.fixture(autouse=True)
def _isolate_app_data(request, _data_sandbox):
    module = request.node.module.__name__.rsplit(".", 1)[-1]
    if module in _EXEMPT_MODULES:
        yield
        return

    original_cwd = Path.cwd()
    os.chdir(_data_sandbox)
    try:
        yield
    finally:
        os.chdir(original_cwd)
