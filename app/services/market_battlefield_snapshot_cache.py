from datetime import datetime


class MarketBattlefieldSnapshotCache:
    _snapshot = None
    _created_at = None
    _ttl_seconds = 900
    _future_tolerance_seconds = 5

    @classmethod
    def get(cls):
        if cls._snapshot is None or cls._created_at is None:
            return None

        now = datetime.utcnow()
        age_seconds = (now - cls._created_at).total_seconds()

        if age_seconds < -cls._future_tolerance_seconds:
            cls._snapshot = None
            cls._created_at = None
            return {
                "snapshot_cache": {
                    "cache_hit": False,
                    "cache_rejected": True,
                    "cache_rejection_reason": "FUTURE_CACHE_TIMESTAMP_DETECTED",
                    "server_now": now.isoformat(),
                    "cache_age_seconds": round(age_seconds, 2),
                    "cache_ttl_seconds": cls._ttl_seconds,
                },
                "system": "GreyLine",
                "battlefield_health": "RED",
                "battlefield_health_reason": "Future cache timestamp rejected.",
                "status": "MARKET_BATTLEFIELD_CACHE_REJECTED",
            }

        if age_seconds > cls._ttl_seconds:
            return None

        snapshot = dict(cls._snapshot)
        cache = {
            "cache_hit": True,
            "cached_at": cls._created_at.isoformat(),
            "server_now": now.isoformat(),
            "cache_age_seconds": round(age_seconds, 2),
            "cache_ttl_seconds": cls._ttl_seconds,
        }
        return {"snapshot_cache": cache, **snapshot}

    @classmethod
    def set(cls, snapshot):
        now = datetime.utcnow()
        cls._snapshot = dict(snapshot)
        cls._created_at = now

        result = dict(snapshot)
        cache = {
            "cache_hit": False,
            "cached_at": cls._created_at.isoformat(),
            "server_now": now.isoformat(),
            "cache_age_seconds": 0,
            "cache_ttl_seconds": cls._ttl_seconds,
        }
        return {"snapshot_cache": cache, **result}

    @classmethod
    def clear(cls):
        cls._snapshot = None
        cls._created_at = None
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "cache_cleared": True,
            "status": "MARKET_BATTLEFIELD_CACHE_CLEARED",
        }
