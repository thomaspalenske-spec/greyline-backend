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
import shutil
from pathlib import Path

import pytest

_SKIP = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}

_EXEMPT_MODULES = {
    "test_credential_security_audit",  # shells out to git in the real repo
    "test_route_audit",                # drives every live route (needs real env)
    "test_schema_audit",               # drives every live route (needs real env)
    "test_end_to_end_trade_readiness", # audits the LIVE trade-firing chain (real data + broker reads)
    "test_risk_budget_sizing_backtest",# reads the real historical CSVs (2013+ crash-year coverage)
    "test_risk_budget_operationalize", # reads the real historical CSVs (advisory vols for the glide plan)
    "test_total_return_signal_impact", # reads the real total-return CSVs (close vs adj_close)
    "test_risk_budget_glide_invariant",# reads the real historical CSVs (advisory vols for the re-mix group)
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


# Every PROCESS-WIDE cache/singleton that must be flushed between tests, as (module, dotted-attr). `self`
# and instances are excluded from these keys, so without a flush one test's cached equity / held positions /
# quotes / greeks / report leaks into the next — the root of the suite's order-dependent failures. Found by
# sweeping app/services for class- and module-level cache dicts; add new ones here when engines gain them.
_ENGINE_CACHES = [
    ("app.services.broker_account_view_engine", "_SNAPSHOT_CACHE"),
    ("app.services.greyline_reality_guard_engine", "_GUARD_CACHE"),
    ("app.services.pre_open_readiness_engine", "_AUDIT_CACHE"),
    ("app.services.adaptive_dte_selection_engine", "AdaptiveDTESelectionEngine._cache"),
    ("app.services.breadth_scoring_engine", "BreadthScoringEngine._quote_context_cache"),
    ("app.services.conditional_vrp_short_premium_engine", "ConditionalVRPShortPremiumEngine._PLAN_CACHE"),
    ("app.services.gex_mean_reversion_shadow_engine", "GexMeanReversionShadowEngine._signals_cache"),
    ("app.services.optionable_universe_engine", "OptionableUniverseEngine._fetch_cache"),
    ("app.services.sleeve_capital_budget_engine", "SleeveCapitalBudgetEngine._cache"),
    ("app.services.sleeve_capital_budget_engine", "SleeveCapitalBudgetEngine._rp_cache"),
    ("app.services.tradestation_positions_live_engine", "TradeStationPositionsLiveEngine._CACHE"),
    ("app.services.tradestation_balance_live_engine", "TradeStationBalanceLiveEngine._CACHE"),
    ("app.services.tradestation_option_chain_live_engine", "TradeStationOptionChainLiveEngine._snap_cache"),
    ("app.services.tradestation_sim_booking_engine", "TradeStationSimBookingEngine._READ_CACHE"),
    ("app.services.tradestation_quote_live_engine", "TradeStationQuoteLiveEngine._quote_cache"),
    ("app.services.uw_option_quote_engine", "UWOptionQuoteEngine._cache"),
    ("app.services.uw_stream_engine", "UWStreamEngine._cache"),
    ("app.services.uw_option_chain_engine", "UWOptionChainEngine._cache"),
]


def _reset_cache_obj(obj):
    """A TTL-dict ({'t'/'at'/'epoch': ts, <payload>}) is invalidated by zeroing its timestamp (keeps the
    required keys present so `cache['t']` never KeyErrors); a plain cache dict is cleared outright."""
    if not isinstance(obj, dict):
        return
    ts_keys = [k for k in ("t", "at", "epoch") if k in obj]
    if ts_keys:
        for k in ts_keys:
            obj[k] = 0.0
    else:
        obj.clear()


def _flush_engine_caches():
    import importlib
    from app.services.ttl_cache import clear_all
    clear_all()                                              # every @ttl_cached report() cache
    for mod_path, dotted in _ENGINE_CACHES:
        try:
            obj = importlib.import_module(mod_path)
            for part in dotted.split("."):
                obj = getattr(obj, part)
            _reset_cache_obj(obj)
        except Exception:
            pass


# Modules that legitimately audit the REAL operator configuration (they drive the live routes / the
# trade-firing chain and assert against the operator's armed state), so the arming/alloc strip below is
# NOT applied to them — only the original 4-flag strip common to every test. Everything else (unit tests,
# and the sizing/backtest modules whose expected numbers are computed for CLEAN defaults) gets the full
# strip so a leaked .env arming flag can never flip their math.
_LIVE_ENV_MODULES = {
    "test_route_audit", "test_schema_audit",
    "test_end_to_end_trade_readiness", "test_credential_security_audit",
}

# The operator's full sleeve arming / allocation / sizing-mode switch set (enumerated from .env). ANY of
# these, once a reload_env() (fired by an earlier VRP/token/route test) has pulled the operator's live .env
# into os.environ, is snapshot-preserved into later tests and silently changes every sizing/gating engine
# that reads os.environ directly (SleeveCapitalBudgetEngine, the risk-budget glide/operationalize/backtest
# engines, momentum, exposure, total-return). Those engines DON'T call reload_env, so stripping the flags
# at test setup holds through the body — restoring the snapshot after brings them back for the next test.
_OPERATOR_ARMING_FLAGS = (
    "GREYLINE_MOMENTUM_ENABLED", "GREYLINE_MOMENTUM_ALLOC_PCT", "GREYLINE_MOMENTUM_BUDGET_SIZING",
    "GREYLINE_MOMENTUM_SCAN_WARM", "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_VRP_ALLOC_PCT",
    "GREYLINE_BROKER_PROTECTIVE_STOPS", "GREYLINE_SLEEVE_RISK_BUDGET", "GREYLINE_PER_SLEEVE_SIZING",
    "GREYLINE_VOL_CARRY_ENABLED", "GREYLINE_VOL_CARRY_ALLOC_PCT", "GREYLINE_VOL_CARRY_ALLOC_USD",
    "GREYLINE_TREND_ENABLED", "GREYLINE_TREND_ALLOC_PCT", "GREYLINE_TREND_ALLOC_USD",
    "GREYLINE_MANAGED_FUTURES_ENABLED", "GREYLINE_MANAGED_FUTURES_ALLOC_PCT",
    "GREYLINE_XSMOM_ENABLED", "GREYLINE_XSMOM_ALLOC_USD",
    "GREYLINE_LOW_VOL_ENABLED", "GREYLINE_LOW_VOL_ALLOC_USD",
    "GREYLINE_EARNINGS_VOL_ENABLED", "GREYLINE_EARNINGS_ALLOC_PCT",
    "GREYLINE_ADAPTIVE_DTE_ENABLED", "GREYLINE_REGIME_GATE_ENABLED",
    "GREYLINE_TBILL_SWEEP_ENABLED", "GREYLINE_INSTITUTIONAL_SWEEP_ENABLED",
    "GREYLINE_MAX_SECTOR_EXPOSURE_PCT", "GREYLINE_CONDOR_MAX_LOSS_PCT",
    "GREYLINE_SIM_BOOKING_ENABLED", "GREYLINE_PAPER_EXECUTION_ENABLED",
    "GREYLINE_LIVE_EXECUTION_ENABLED", "GREYLINE_LIVE_TRADING_ENABLED",
    "GREYLINE_FLATTEN_ALL_ENABLED", "GREYLINE_LEGACY_LIQUIDATION_ENABLED",
)


@pytest.fixture(autouse=True)
def _isolate_os_environ(request):
    """Snapshot and restore os.environ around each test. reload_env() writes directly into os.environ (the
    documented .env-precedence trap), NOT through monkeypatch — so without this a test that triggers a
    reload re-populates the operator's .env values (armed sleeve flags, alloc pins) and they persist into
    later tests, flipping their expectations. Restoring the snapshot contains those direct mutations."""
    saved = dict(os.environ)
    # Strip operator arming/alloc/sizing flags DIRECTLY from os.environ (not via monkeypatch, which fixture
    # ordering can undo): they live in the operator's .env, so an earlier reload_env() pulls them in and they
    # persist. Removing them at setup guarantees every test body sees CLEAN DEFAULTS unless the test sets a
    # flag itself; the snapshot restore below brings them back after. The live-env audit modules are exempt
    # from the full strip — they assert against the operator's real armed config — so they keep only the
    # long-standing momentum/vrp/protective-stops strip that has always applied suite-wide.
    module = request.node.module.__name__.rsplit(".", 1)[-1]
    if module in _LIVE_ENV_MODULES:
        for _k in ("GREYLINE_MOMENTUM_ENABLED", "GREYLINE_MOMENTUM_ALLOC_PCT",
                   "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_BROKER_PROTECTIVE_STOPS"):
            os.environ.pop(_k, None)
    else:
        for _k in _OPERATOR_ARMING_FLAGS:
            os.environ.pop(_k, None)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _flush_ttl_caches():
    """Flush EVERY process-wide in-memory cache before AND after each test so state can't leak across cases
    — the root of the suite's order-dependent failures (a test's cached equity/held-positions/report bleeds
    into the next). Clearing (not disabling) keeps within-test caching intact; production never calls this."""
    _flush_engine_caches()
    yield
    _flush_engine_caches()


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
              # operator arming flags for real-order-placing features must never leak into tests — a sleeve
              # armed in the operator's .env (e.g. momentum, re-armed 2026-08-17) would otherwise flip the
              # "disabled path" unit tests, which expect the flag OFF unless the test itself sets it.
              "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_BROKER_PROTECTIVE_STOPS",
              "GREYLINE_MOMENTUM_ENABLED", "GREYLINE_MOMENTUM_ALLOC_PCT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GREYLINE_ALERT_MACOS_LOCAL", "false")
    # Disable the shadow report() TTL cache in tests: several tests call report() twice in one test and
    # assert it reflects freshly-written state between the calls (e.g. NO_DATA -> MEASURING). clear_all()
    # only flushes BETWEEN tests, so the within-test cache would return the stale first result. (Uses the
    # shadow key only; test_ttl_cache exercises the decorator via its own GREYLINE_TEST_TTL key.)
    monkeypatch.setenv("GREYLINE_SHADOW_CACHE_TTL", "0")

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
        # Exempt modules read the REAL app/data at the repo root (historical CSVs, git, .env). GUARANTEE that
        # cwd rather than inheriting whatever a prior test left: engines resolve reference data through
        # cwd-relative paths (e.g. SleeveCapitalBudgetEngine._HIST = Path("app/data/historical")), and an
        # earlier test's monkeypatch.chdir (test_account_return_horizon chdirs into a tmp dir) leaves cwd
        # outside the repo. An exempt test then reads an EMPTY app/data and silently collapses — the
        # risk-parity advisory falls to INSUFFICIENT_VOL_DATA, so the sizing/glide/total-return assertions
        # fail order-dependently (pass alone, fail after the chdir'ing test). Pin cwd to the real root.
        real_root = Path(__file__).resolve().parents[1]
        original_cwd = Path.cwd()
        os.chdir(real_root)
        try:
            yield
        finally:
            os.chdir(original_cwd)
        return

    # RESET app/data to empty before each test. The sandbox is session-scoped for speed, so without this the
    # persisted ledgers/state one test writes (e.g. a rebalance's opened positions) leak into the next — a
    # test opens into "free slots", the next sees them already held and opens nothing. Wiping restores the
    # fresh-empty app/data every engine expects at start, giving per-test isolation of mutable state without
    # re-symlinking the whole repo per test. (app/data holds only real files here — nothing symlinked.)
    data_dir = _data_sandbox / "app" / "data"
    if data_dir.exists():
        for child in data_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    else:
        data_dir.mkdir(parents=True, exist_ok=True)

    original_cwd = Path.cwd()
    os.chdir(_data_sandbox)
    try:
        yield
    finally:
        os.chdir(original_cwd)
