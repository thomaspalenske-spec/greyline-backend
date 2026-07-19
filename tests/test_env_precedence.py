import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import env_reload


def _write_env(tmp_path, body):
    p = tmp_path / ".env"
    p.write_text(body)
    return str(p)


def test_reload_env_refreshes_rotated_tokens(tmp_path, monkeypatch):
    """The reason engines re-read .env at all: set_key rotates the access token on disk
    and an engine constructed afterwards must see the new value."""
    monkeypatch.setattr(env_reload, "_EXPORTED", frozenset())
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "stale")
    env_reload.reload_env(_write_env(tmp_path, "TRADESTATION_ACCESS_TOKEN=rotated\n"))
    assert os.getenv("TRADESTATION_ACCESS_TOKEN") == "rotated"


def test_reload_env_never_overrides_an_exported_variable(tmp_path, monkeypatch):
    """The kill switch must hold. Exporting the flag false has to survive every engine
    construction, or `export GREYLINE_SIM_BOOKING_ENABLED=false` silently keeps booking."""
    monkeypatch.setattr(env_reload, "_EXPORTED", frozenset({"GREYLINE_SIM_BOOKING_ENABLED"}))
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "false")
    env_reload.reload_env(_write_env(tmp_path, "GREYLINE_SIM_BOOKING_ENABLED=true\n"))
    assert os.getenv("GREYLINE_SIM_BOOKING_ENABLED") == "false"


def test_env_file_still_drives_unexported_flags(tmp_path, monkeypatch):
    """Editing .env remains the supported way to flip the switches in production, where
    nothing is exported (the launchd plist sets no EnvironmentVariables)."""
    monkeypatch.setattr(env_reload, "_EXPORTED", frozenset())
    monkeypatch.delenv("GREYLINE_SIM_BOOKING_ENABLED", raising=False)
    env_reload.reload_env(_write_env(tmp_path, "GREYLINE_SIM_BOOKING_ENABLED=true\n"))
    assert os.getenv("GREYLINE_SIM_BOOKING_ENABLED") == "true"


def test_constructing_an_engine_does_not_revert_an_exported_flag(tmp_path, monkeypatch):
    """End-to-end over the real call site that caused the bug: the exit manager builds a
    quote engine before mirroring exits, and that construction used to clobber the flag."""
    monkeypatch.setattr(env_reload, "_EXPORTED", frozenset({"GREYLINE_SIM_BOOKING_ENABLED"}))
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "false")
    from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine

    TradeStationQuoteLiveEngine()
    assert os.getenv("GREYLINE_SIM_BOOKING_ENABLED") == "false"
