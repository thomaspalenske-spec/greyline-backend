"""Single source of truth for re-reading .env inside a long-running process.

Tokens rotate: the token refresh/exchange engines write a fresh access token into .env
with set_key, and engines constructed later must see it. That is the reason the broker
engines re-read .env on construction at all.

They used to do it with load_dotenv(override=True), which reloaded the token but also
clobbered every OTHER variable — silently reverting anything the operator had exported
into the process back to the file's value. That broke the precedence main.py declares
("a real shell export still wins over .env") in the most dangerous direction: exporting
GREYLINE_SIM_BOOKING_ENABLED=false to stop booking did nothing once .env said true, and
the revert happened on the next engine construction, so it looked like it had worked.

reload_env() keeps the refresh and restores the precedence: variables the operator
exported win permanently, everything else tracks .env — so editing .env still takes
effect in a running process, which is how the GREYLINE_* switches are meant to be flipped.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

# Captured at import time. main.py imports this module before it loads .env, so these are
# the variables that were genuinely exported into the process — never file-sourced ones.
_EXPORTED = frozenset(os.environ)


def exported_keys():
    """The process-env variables that .env is not allowed to override (diagnostics)."""
    return _EXPORTED


def reload_env(path=".env"):
    """Re-read .env for rotated credentials without overriding exported variables."""
    for key, value in dotenv_values(dotenv_path=Path(path)).items():
        if value is None or key in _EXPORTED:
            continue
        os.environ[key] = value
