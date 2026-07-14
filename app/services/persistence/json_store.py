"""
Durable, self-healing JSON persistence.

Two guarantees the raw `json.dump` / `read_text` pattern does NOT provide:

1. ATOMIC writes — data is written to a temp file in the same directory, fsync'd,
   then os.replace()'d into place. A crash mid-write can never leave a truncated /
   corrupt file at the real path (the failure mode that crashed the snapshot repo).

2. SELF-HEALING reads — a missing, empty, or corrupt file returns the caller's
   default instead of raising. A corrupt file is preserved as `<name>.corrupt` for
   forensics so nothing is silently lost.

Stdlib only. Safe to adopt incrementally across the existing file-backed repositories.
"""
import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path, data, indent=2):
    """Write `data` as JSON to `path` atomically and durably."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on the same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path, text):
    """Write raw text (e.g. a rebuilt JSONL body) atomically and durably."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path, obj):
    """Append one JSON object as a line to a JSONL file (durable, mkdirs)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path):
    """Read a JSONL file tolerantly: missing file -> [], corrupt lines skipped."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            pass
    return rows


def _resolve_default(default):
    return default() if callable(default) else default


def read_json(path, default=None, normalizer=None):
    """
    Read JSON from `path`, tolerating missing / empty / corrupt files.

    - missing or empty -> `default` (a value, or a zero-arg callable for fresh mutables)
    - corrupt          -> back up to `<name>.corrupt`, then return `default`
    - `normalizer`     -> optional callable applied to the loaded value (e.g. to
                          coerce a legacy top-level list into {"items": [...]})
    """
    path = Path(path)

    if not path.exists():
        value = _resolve_default(default)
        return normalizer(value) if normalizer else value

    try:
        raw = path.read_text()
        value = json.loads(raw) if raw.strip() else _resolve_default(default)
    except (json.JSONDecodeError, ValueError, OSError):
        try:
            path.replace(path.with_name(path.name + ".corrupt"))
        except OSError:
            pass
        value = _resolve_default(default)

    return normalizer(value) if normalizer else value
