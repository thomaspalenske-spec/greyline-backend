from datetime import datetime
from pathlib import Path

from app.services.persistence.json_store import append_jsonl, read_jsonl


def _parse(ts):
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])
    except Exception:
        return None


class PriceHistoryStore:
    """
    Durable per-symbol price time-series: `(timestamp, price)` points, append-only.

    Enables FIXED-HORIZON outcome grading: given a decision at time T, look up the
    price at T + horizon (`price_at`) instead of "current price whenever the grader
    runs" — the confound that made GreyLine's edge unmeasurable.

    Points come from two sources: live recording each scheduler cycle (forward), and
    a one-time bootstrap from the snapshot prices already embedded in decision logs.
    """

    def __init__(self, base_dir="app/data/price_history"):
        self.base_dir = Path(base_dir)

    def _path(self, symbol):
        return self.base_dir / f"{str(symbol).upper().strip()}.jsonl"

    def record(self, symbol, price, timestamp=None):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return False
        if price <= 0 or not symbol:
            return False
        ts = timestamp or datetime.utcnow().isoformat()
        append_jsonl(self._path(symbol), {"ts": ts, "price": price})
        return True

    def record_batch(self, points):
        """points: iterable of (symbol, price, timestamp). Returns count recorded."""
        n = 0
        for symbol, price, ts in points:
            if self.record(symbol, price, ts):
                n += 1
        return n

    def _load(self, symbol):
        rows = read_jsonl(self._path(symbol))
        out = []
        for r in rows:
            dt = _parse(r.get("ts"))
            price = r.get("price")
            if dt is not None and isinstance(price, (int, float)) and price > 0:
                out.append((dt, float(price)))
        out.sort(key=lambda x: x[0])
        return out

    def price_at(self, symbol, target_timestamp, max_tolerance_seconds=3600,
                 direction="nearest"):
        """
        Nearest recorded price to `target_timestamp` within tolerance.

        `direction` constrains WHICH side of the target is acceptable:
          "nearest" - either side (the historical default)
          "before"  - at or before the target; use for ENTRY / decision-time prices
          "after"   - at or after the target;  use for OUTCOME / T+horizon prices

        This matters because the match was previously two-sided and the returned age was
        absolute, so a caller could not tell whether it got a price from before or after
        the moment it asked about. An entry price sampled an hour LATE leaks the outcome
        into the entry and inflates apparent skill on any momentum-derived signal; an
        outcome price sampled early shortens the horizon it claims to measure.

        Returns {price, timestamp, age_seconds, is_after} or None. `age_seconds` is SIGNED:
        negative means the matched point precedes the target, positive means it follows.
        """
        target = _parse(target_timestamp)
        if target is None:
            return None
        points = self._load(symbol)
        if not points:
            return None

        if direction == "before":
            points = [p for p in points if p[0] <= target]
        elif direction == "after":
            points = [p for p in points if p[0] >= target]
        if not points:
            return None

        best = min(points, key=lambda p: abs((p[0] - target).total_seconds()))
        delta = (best[0] - target).total_seconds()
        if abs(delta) > max_tolerance_seconds:
            return None
        return {"price": best[1], "timestamp": best[0].isoformat(),
                "age_seconds": round(delta, 1), "is_after": delta > 0}

    def coverage(self, symbol):
        points = self._load(symbol)
        if not points:
            return {"symbol": str(symbol).upper(), "points": 0, "first": None, "last": None}
        return {
            "symbol": str(symbol).upper(),
            "points": len(points),
            "first": points[0][0].isoformat(),
            "last": points[-1][0].isoformat(),
        }
