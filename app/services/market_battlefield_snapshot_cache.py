from datetime import datetime
import json
from pathlib import Path


class MarketBattlefieldSnapshotCache:
    _snapshot = None
    _created_at = None
    _ttl_seconds = 900
    _future_tolerance_seconds = 5
    _cache_path = Path("app/data/market_battlefield_snapshot_cache.json")

    @classmethod
    def _load_file(cls):
        if not cls._cache_path.exists():
            return None, None
        try:
            data = json.loads(cls._cache_path.read_text())
            snapshot = data.get("snapshot")
            created_at_raw = data.get("created_at")
            created_at = datetime.fromisoformat(created_at_raw) if created_at_raw else None
            return snapshot, created_at
        except Exception:
            return None, None

    @classmethod
    def get(cls):
        if cls._snapshot is None or cls._created_at is None:
            cls._snapshot, cls._created_at = cls._load_file()

        if cls._snapshot is None or cls._created_at is None:
            return None

        now = datetime.utcnow()
        age_seconds = (now - cls._created_at).total_seconds()

        if age_seconds < -cls._future_tolerance_seconds:
            cls.clear()
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
        cls._cache_path.parent.mkdir(parents=True, exist_ok=True)
        cls._cache_path.write_text(json.dumps({
            "created_at": cls._created_at.isoformat(),
            "snapshot": cls._snapshot,
        }, indent=2, default=str))

        cache = {
            "cache_hit": False,
            "cached_at": cls._created_at.isoformat(),
            "server_now": now.isoformat(),
            "cache_age_seconds": 0,
            "cache_ttl_seconds": cls._ttl_seconds,
        }
        return {"snapshot_cache": cache, **dict(snapshot)}

    @classmethod
    def clear(cls):
        cls._snapshot = None
        cls._created_at = None
        try:
            cls._cache_path.unlink(missing_ok=True)
        except TypeError:
            if cls._cache_path.exists():
                cls._cache_path.unlink()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "cache_cleared": True,
            "status": "MARKET_BATTLEFIELD_CACHE_CLEARED",
        }
