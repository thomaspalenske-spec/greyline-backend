"""Bounded HTTP GET for scheduler-cycle reads.

Two protections, extracted from the 2026-08-11 broker/UW cycle-freeze fixes so every cycle HTTP read can
be bounded the same way (the general rule that incident cemented):

  * TOTAL wall-clock deadline over the WHOLE request INCLUDING the streamed body read. `requests`' timeout
    is only *between-bytes*, so a trickling / half-open response never trips it and hangs the caller
    forever — which froze the scheduler cycle. `bounded_get` streams the body and aborts at the deadline.
  * keyed SINGLE-FLIGHT so a burst of concurrent same-key callers coalesce into one upstream fetch instead
    of stampeding it (the thundering herd that exhausted the process's connections).
"""

import os
import threading
import time

import requests


def envf(name, default):
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return float(default)


def bounded_get(getter, url, *, params=None, headers=None,
                connect_timeout=6.0, read_timeout=10.0, total_deadline=25.0):
    """GET with a TOTAL wall-clock deadline over the whole request incl. the streamed body read.

    `getter` is anything with a requests-style `.get` (a `requests.Session`, or the `requests` module
    itself). Returns `(response, body_bytes)`; the connection is ALWAYS released. Raises
    `requests.exceptions.Timeout` if the total deadline is exceeded while reading the body.
    """
    deadline = time.monotonic() + total_deadline
    resp = getter.get(url, params=params, headers=headers,
                      timeout=(connect_timeout, read_timeout), stream=True)
    try:
        chunks = []
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
            if time.monotonic() > deadline:
                raise requests.exceptions.Timeout(
                    f"total-request deadline {total_deadline:.0f}s exceeded reading body from {url}")
        return resp, b"".join(chunks)
    finally:
        resp.close()


class KeyedSingleFlight:
    """One `Lock` per key so concurrent same-key fetches coalesce; different keys never block each other.
    Soft-capped so the lock map can't grow without bound over a long-lived process (a rare reset only loses
    coalescing briefly; correctness holds)."""

    def __init__(self, cap=8192):
        self._locks = {}
        self._guard = threading.Lock()
        self._cap = cap

    def lock(self, key):
        with self._guard:
            if len(self._locks) > self._cap:
                self._locks.clear()
            lk = self._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._locks[key] = lk
            return lk
