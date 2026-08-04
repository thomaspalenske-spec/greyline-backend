"""_chain must NEVER fall to the slow TS adaptive-DTE grind when UW is enabled — profiling proved that
fallback (N tenors x a slow SIM stream per name) was the entire ~164-min heavy-block cost. UW-enabled:
use UW or SKIP; only when UW is unavailable (no key) does the TS degraded path run."""

import app.services.uw_option_chain_engine as uwmod
import app.services.adaptive_dte_selection_engine as adte
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _uw(enabled, contracts):
    class UW:
        def enabled(self): return enabled
        def monthly_expiry(self, target_dte=42): return "2026-09-18"
        def get_chain_snapshot(self, symbol, expiration): return {"contracts": contracts}
    return UW


def test_uw_enabled_empty_skips_never_ts(monkeypatch):
    monkeypatch.setattr(uwmod, "UWOptionChainEngine", _uw(True, []))     # UW up but can't price this name
    hit = {"ts": False}
    monkeypatch.setattr(adte.AdaptiveDTESelectionEngine, "select",
                        lambda self, s: hit.__setitem__("ts", True) or "x")
    exp, contracts = V()._chain("SPY")
    assert exp is None and contracts == []          # skipped
    assert hit["ts"] is False                        # the slow TS adaptive path was NEVER touched


def test_uw_enabled_with_contracts_uses_uw(monkeypatch):
    monkeypatch.setattr(uwmod, "UWOptionChainEngine", _uw(True, [{"Side": "Call"}]))
    hit = {"ts": False}
    monkeypatch.setattr(adte.AdaptiveDTESelectionEngine, "select",
                        lambda self, s: hit.__setitem__("ts", True) or "x")
    exp, contracts = V()._chain("SPY")
    assert exp == "2026-09-18" and len(contracts) == 1 and hit["ts"] is False


def test_uw_disabled_uses_ts_degraded(monkeypatch):
    monkeypatch.setattr(uwmod, "UWOptionChainEngine", _uw(False, []))   # no UW key -> degraded mode
    import app.services.tradestation_option_chain_live_engine as tsmod
    monkeypatch.setattr(adte.AdaptiveDTESelectionEngine, "select", lambda self, s: "2026-09-18")
    monkeypatch.setattr(tsmod.TradeStationOptionChainLiveEngine, "get_chain_snapshot",
                        lambda self, **kw: {"contracts": [{"Side": "Put"}]})
    exp, contracts = V()._chain("SPY")
    assert exp == "2026-09-18" and len(contracts) == 1                   # TS path only when UW unavailable
