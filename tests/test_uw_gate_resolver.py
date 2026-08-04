"""UW capability gates must resolve the API key the SAME way the provider does (.env + .env.local, local
wins) so a gate can never read 'disabled' while the provider actually works — the divergence that silently
dropped the VRP/earnings condor build to the slow, unusable TradeStation SIM fallback."""

import app.services.env_reload as er
from app.services.uw_option_chain_engine import UWOptionChainEngine
from app.services.uw_option_quote_engine import UWOptionQuoteEngine


def test_gates_agree_with_shared_resolver():
    # whatever the shared resolver says about key presence, BOTH gates must agree — no independent getenv.
    present = bool(er.uw_api_key())
    assert UWOptionChainEngine().enabled() is present
    assert UWOptionQuoteEngine().enabled() is present


def test_resolver_self_loads_key_from_env_local(monkeypatch):
    # Simulate the exact divergence: the key is ONLY in .env.local (not ambient env, not .env). The gate
    # must still read enabled=True because uw_api_key() self-loads .env.local like the provider.
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    calls = {"n": 0}
    real_reload = er.reload_env

    def fake_reload(path=".env"):
        calls["n"] += 1
        if str(path).endswith(".env.local"):
            import os
            os.environ["UNUSUAL_WHALES_API_KEY"] = "from_env_local_xxxxxxxxxxxxxxxxxxxx"

    monkeypatch.setattr(er, "reload_env", fake_reload)
    key = er.uw_api_key()
    assert key == "from_env_local_xxxxxxxxxxxxxxxxxxxx"
    assert calls["n"] >= 2                         # loaded .env AND .env.local


def test_resolver_returns_empty_when_no_key(monkeypatch):
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    monkeypatch.setattr(er, "reload_env", lambda path=".env": None)   # neither file supplies it
    assert er.uw_api_key() == ""
    assert UWOptionChainEngine().enabled() is False                   # honestly disabled, not flaky
