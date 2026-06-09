import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


def test_token_refresh_engine_returns_dict_safely():
    engine = TradeStationTokenRefreshEngine()

    result = engine.refresh()

    assert isinstance(result, dict)
    assert "token_refreshed" in result


def test_token_refresh_engine_does_not_expose_secret_fields():
    engine = TradeStationTokenRefreshEngine()

    result = engine.refresh()
    result_text = str(result).lower()

    assert "client_secret" not in result_text
    assert "refresh_token" not in result_text
    assert "access_token" not in result_text
