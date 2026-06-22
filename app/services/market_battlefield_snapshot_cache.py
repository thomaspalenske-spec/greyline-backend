from datetime import datetime, timedelta


class MarketBattlefieldSnapshotCache:
    _snapshot = None
    _created_at = None

    @classmethod
    def get(cls):
        if cls._snapshot is None or cls._created_at is None:
            return None

        age_seconds = (datetime.utcnow() - cls._created_at).total_seconds()

        if age_seconds > 120:
            return None

        snapshot = dict(cls._snapshot)
        cache = {
            "cache_hit": True,
            "cached_at": cls._created_at.isoformat(),
            "cache_age_seconds": round(age_seconds, 2),
            "cache_ttl_seconds": 120,
        }
        return {"snapshot_cache": cache, **snapshot}

    @classmethod
    def set(cls, snapshot):
        cls._snapshot = dict(snapshot)
        cls._created_at = datetime.utcnow()

        result = dict(snapshot)
        cache = {
            "cache_hit": False,
            "cached_at": cls._created_at.isoformat(),
            "cache_age_seconds": 0,
            "cache_ttl_seconds": 120,
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
