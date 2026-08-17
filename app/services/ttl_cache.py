"""A tiny short-TTL single-flight cache decorator for READ-ONLY, slow-moving report methods.

Motivation (2026-08-16 incident): the operator dashboard auto-refreshes ~30 cards, and several are
shadow/court `report()` methods that recompute from scratch (UW option chains, greeks, quotes) on every
poll. A refresh burst fired many concurrent recomputes and pegged a core. These forward-test surfaces
change on the order of minutes-to-days, so serving a few-seconds-stale snapshot is harmless — and a
single-flight lock means N concurrent pollers trigger ONE recompute, not N.

Use on a zero/low-arg instance method whose result is safe to reuse briefly:
    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self): ...

`self` is excluded from the cache key, so all callers/instances share one cached result. env_key (if
given and set) overrides the default TTL; 0 disables the cache (kill switch). Never caches an exception.
"""

import threading
import time
from os import getenv


def ttl_cached(seconds=30.0, env_key=None):
    def deco(fn):
        cache = {}                 # (args_excl_self, kwargs) -> (monotonic_ts, result)
        lock = threading.Lock()

        def _ttl():
            if env_key:
                v = getenv(env_key, "")
                if str(v).strip() != "":
                    try:
                        return max(0.0, float(v))
                    except (TypeError, ValueError):
                        pass
            return seconds

        def wrapper(*args, **kwargs):
            ttl = _ttl()
            key = (args[1:], tuple(sorted(kwargs.items())))     # drop self at args[0]
            if ttl > 0:
                hit = cache.get(key)
                if hit and (time.monotonic() - hit[0]) < ttl:
                    return hit[1]
            with lock:                                          # single-flight the recompute
                if ttl > 0:
                    hit = cache.get(key)
                    if hit and (time.monotonic() - hit[0]) < ttl:
                        return hit[1]
                result = fn(*args, **kwargs)                    # an exception propagates, never cached
                if ttl > 0:
                    cache[key] = (time.monotonic(), result)
                return result

        wrapper.__name__ = getattr(fn, "__name__", "ttl_cached")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        wrapper.__wrapped__ = fn
        wrapper._ttl_cache = cache                              # exposed for tests / manual invalidation
        return wrapper

    return deco
