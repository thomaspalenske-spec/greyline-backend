"""Low-vol / BAB sleeve: inverse-volatility weighting (more capital to lower-vol names), fail-safe when
price data is missing (no weights -> no targets -> no trades), and gated OFF by default."""

from app.services.low_volatility_engine import LowVolatilityEngine as L


def test_inverse_vol_weighting(monkeypatch):
    monkeypatch.setattr(L, "_realized_vol",
                        lambda self, s: {"USMV": 0.10, "SPLV": 0.10, "EFAV": 0.20, "XMLV": 0.40}.get(s))
    w, vols = L()._weights()
    assert abs(sum(w.values()) - 1.0) < 1e-9                 # weights normalize
    assert w["USMV"] > w["EFAV"] > w["XMLV"]                 # lower vol -> more weight (the low-vol tilt)
    assert abs(w["USMV"] - w["SPLV"]) < 1e-9                 # equal vol -> equal weight


def test_missing_data_fails_safe(monkeypatch):
    monkeypatch.setattr(L, "_realized_vol", lambda self, s: None)   # no usable vol for any name
    w, _ = L()._weights()
    assert w == {}                                          # no targets -> the sleeve never trades on no data


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GREYLINE_LOW_VOL_ENABLED", raising=False)
    assert L.enabled() is False
    assert L().run_cycle()["status"] == "LOW_VOL_DISABLED"   # short-circuits before any broker call


def test_registered_in_edge_proof_protocol():
    from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine
    assert "low_vol" in EdgeProofProtocolEngine.DEFAULTS      # has a pre-registered kill-rule from day one
