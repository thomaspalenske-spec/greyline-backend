from datetime import datetime
from pathlib import Path

from app.services.persistence.json_store import read_jsonl


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])
    except Exception:
        return None


class ContinuityMonitorEngine:
    """
    Did GreyLine actually keep accumulating, or were there gaps?

    Continuity is the whole point of running as a service — but a gap (a laptop
    sleep, a reboot, a crash) leaves no error, just missing data that looks
    identical to a quiet market. This reads the per-cycle heartbeat and finds the
    holes: where the interval between beats blew past the normal cadence.

    Self-calibrating: the "normal" cadence is the median interval between beats, so
    this adapts to whatever the real cycle time is instead of a guessed constant. A
    gap is an interval longer than `gap_factor` x median (with a floor), which is a
    genuine stoppage rather than ordinary jitter.
    """

    HEARTBEAT = Path("app/data/continuity/heartbeat.jsonl")

    def __init__(self, lookback=3000, gap_factor=4.0, floor_minutes=15.0):
        self.lookback = lookback
        self.gap_factor = gap_factor
        self.floor_minutes = floor_minutes

    def diagnose(self, now=None):
        now = now or datetime.utcnow()
        beats = read_jsonl(self.HEARTBEAT)[-self.lookback:]
        times = sorted(t for t in (_parse(b.get("at")) for b in beats) if t is not None)

        if len(times) < 2:
            return {
                "timestamp": now.isoformat(),
                "source": "CONTINUITY_MONITOR",
                "verdict": "UNKNOWN",
                "headline": "Not enough heartbeat history yet to judge continuity.",
                "beats": len(times),
                "status": "CONTINUITY_MONITOR_WARMING_UP",
            }

        intervals = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
        ordered = sorted(intervals)
        median = ordered[len(ordered) // 2]
        threshold_s = max(median * self.gap_factor, self.floor_minutes * 60)

        gaps = []
        for i in range(1, len(times)):
            dur = (times[i] - times[i - 1]).total_seconds()
            if dur > threshold_s:
                gaps.append({
                    "from": times[i - 1].isoformat(),
                    "to": times[i].isoformat(),
                    "minutes": round(dur / 60, 1),
                })

        span_s = (times[-1] - times[0]).total_seconds()
        downtime_s = sum(g["minutes"] * 60 for g in gaps)
        uptime_pct = round(100 * (span_s - downtime_s) / span_s, 2) if span_s else 100.0

        # Is it beating right now? A stale last beat means it is down at this moment,
        # which is more urgent than a healed historical gap.
        last_age_s = (now - times[-1]).total_seconds()
        currently_live = last_age_s <= threshold_s

        largest = max((g["minutes"] for g in gaps), default=0.0)

        if not currently_live:
            verdict = "RED"
            headline = (
                f"Accumulation is STALLED right now — last heartbeat "
                f"{round(last_age_s / 60, 1)} min ago (cadence ~{round(median / 60, 1)} min)."
            )
        elif gaps:
            verdict = "AMBER"
            headline = (
                f"Live now, but {len(gaps)} gap(s) in the recorded window — "
                f"largest {largest} min. Those periods have missing data."
            )
        else:
            verdict = "GREEN"
            headline = f"Continuous — {len(times)} beats, no gaps beyond normal cadence."

        return {
            "timestamp": now.isoformat(),
            "source": "CONTINUITY_MONITOR",
            "verdict": verdict,
            "headline": headline,
            "beats": len(times),
            "monitored_span_hours": round(span_s / 3600, 1),
            "median_cadence_minutes": round(median / 60, 2),
            "gap_threshold_minutes": round(threshold_s / 60, 1),
            "currently_live": currently_live,
            "last_beat_age_minutes": round(last_age_s / 60, 1),
            "gap_count": len(gaps),
            "largest_gap_minutes": largest,
            "total_downtime_minutes": round(downtime_s / 60, 1),
            "uptime_pct": uptime_pct,
            "recent_gaps": gaps[-10:],
            "status": "CONTINUITY_MONITOR_READY",
        }
