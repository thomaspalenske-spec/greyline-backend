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
