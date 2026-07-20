from datetime import datetime, timedelta
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.skill_metrics_engine import SkillMetricsEngine
from app.services.validation_dedup import dedupe_by_symbol_time

BULLISH = "BULLISH"
BEARISH = "BEARISH"

# (display name, shadow-log field). None field => use a direction field directly.
FEEDS = [
    ("momentum_proxy", "@momentum_direction"),
    ("flow_buying_vs_selling", "@flow_direction"),
    ("greek_flow", "greek_flow_score"),
    ("spot_gamma_gex", "spot_gamma_score"),
    ("lit_flow", "lit_flow_score"),
]


class PerFeedSkillEngine:
    """
    Feature-importance study: for EACH institutional feed, grade its directional call
    against fixed-horizon outcomes and rank by MCC — so we learn which specific signal
    (greek flow / GEX / lit flow / buying / momentum) actually predicts direction.

    Score feeds are 0-100 with >50 = bullish; a neutral band around 50 is skipped.
    Direction feeds (momentum/flow) use their recorded BULLISH/BEARISH label directly.
    """

    def __init__(self, horizon_hours=24, tolerance_hours=6, band_pct=1.0, neutral_band=2.0):
        self.horizon_hours = float(horizon_hours)
        self.tolerance_hours = float(tolerance_hours)
        # Tolerance was pinned at 6h while horizon_hours is caller-controlled from the
        # route with no floor, so GET /feature-skill?horizon_hours=1 accepted a "forward"
        # price from T-5h — an MCC computed on time-reversed data, reported as a 1-hour
        # horizon. Clamp rather than raise so the public route degrades instead of 500ing.
        if self.tolerance_hours >= self.horizon_hours:
            self.tolerance_hours = self.horizon_hours / 4
        self.band_pct = float(band_pct)
        self.neutral_band = float(neutral_band)
        self.ledger = Path("app/data/decision_shadow/decision_shadow_log.jsonl")
        self.price_ledger = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.store = PriceHistoryStore()

    # --- price index (shadow prices + live-recorded price history) ---
    def _price_index(self, symbols):
        idx = {}
        for d in read_jsonl(self.price_ledger):
            self._add(idx, d.get("symbol"), d.get("snapshot_price"), d.get("timestamp"))
        for sym in symbols:
            for dt, price in self.store._load(sym):
                idx.setdefault(sym.upper(), []).append((dt, price))
        for pts in idx.values():
            pts.sort(key=lambda x: x[0])
        return idx

    @staticmethod
    def _add(idx, symbol, price, ts):
        if not symbol or price in (None, 0):
            return
        dt = _parse(ts)
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if dt is None or price <= 0:
            return
        idx.setdefault(str(symbol).upper(), []).append((dt, price))

    def _price_at(self, idx, symbol, target_dt, direction="nearest"):
        """Price near target_dt. `direction` constrains which side is acceptable.

        This duplicated PriceHistoryStore.price_at but dropped its direction= parameter —
        the very thing that function documents as the fix. Two-sided matching let the
        ENTRY price be sampled up to tolerance_hours AFTER the decision, so for
        momentum_proxy and flow_direction (both derived from recent price action) the
        entry already contained the move being graded. It also made the "24h" return span
        anything from 12h to 36h, varying by which symbols happened to have points recorded.
        """
        pts = idx.get(str(symbol).upper())
        if not pts:
            return None
        if direction == "before":
            pts = [p for p in pts if p[0] <= target_dt]
        elif direction == "after":
            pts = [p for p in pts if p[0] >= target_dt]
        if not pts:
            return None
        best = min(pts, key=lambda p: abs((p[0] - target_dt).total_seconds()))
        if abs((best[0] - target_dt).total_seconds()) > self.tolerance_hours * 3600:
            return None
        return best[1]

    def _feed_direction(self, entry, field):
        if field.startswith("@"):
            d = str(entry.get(field[1:]) or "").upper()
            return d if d in (BULLISH, BEARISH) else None
        score = entry.get(field)
        if not isinstance(score, (int, float)):
            return None
        if score > 50 + self.neutral_band:
            return BULLISH
        if score < 50 - self.neutral_band:
            return BEARISH
        return None

    def _grade(self, direction, raw):
        directional = raw if direction == BULLISH else -raw
        if directional >= self.band_pct:
            return "FAVORABLE"
        if directional <= -self.band_pct:
            return "UNFAVORABLE"
        return "NEUTRAL"

    def evaluate(self):
        raw_entries = read_jsonl(self.ledger)
        entries = dedupe_by_symbol_time(raw_entries)  # independent obs (1 per symbol/minute)
        symbols = {str(e.get("symbol")).upper() for e in entries if e.get("symbol")}
        idx = self._price_index(symbols)
        horizon = timedelta(hours=self.horizon_hours)

        # precompute the forward move per entry (shared across feeds)
        moves = []
        for e in entries:
            ts = _parse(e.get("timestamp"))
            if ts is None:
                continue
            cur = self._price_at(idx, e.get("symbol"), ts, direction="before")
            fwd = self._price_at(idx, e.get("symbol"), ts + horizon, direction="after")
            if not cur or not fwd:
                continue
            moves.append((e, (fwd / cur - 1) * 100, str(e.get("symbol") or "").upper(),
                          ts.date().isoformat()))

        feeds = {}
        for name, field in FEEDS:
            graded = []
            for e, raw, _sym, _day in moves:
                direction = self._feed_direction(e, field)
                if direction not in (BULLISH, BEARISH):
                    continue
                graded.append({"directional_bias": direction,
                               "grade": self._grade(direction, raw),
                               "symbol": _sym, "day": _day})
            # dedupe_by_symbol_time only collapses duplicates within the same MINUTE. It
            # does nothing about the two real correlations: one symbol graded hourly over a
            # 24h horizon produces rows whose forward windows overlap by 23/24ths, and all
            # symbols in a cycle share one market move. Passing raw row counts let a feed
            # with no edge post p<0.05 and earn DIRECTIONAL_SKILL_CONFIRMED — which this
            # engine's own interpretation string then calls a candidate to wire into the
            # live decision.
            effective_n = len({(g["symbol"], g["day"]) for g in graded
                               if g["grade"] in ("FAVORABLE", "UNFAVORABLE")})
            skill = SkillMetricsEngine().evaluate(graded, effective_n=effective_n)
            feeds[name] = {
                "mcc": skill.get("mcc"),
                "verdict": skill.get("verdict"),
                "n_decisive": skill["confusion_matrix"]["n_decisive"],
                # Forwarded because the metrics engine added them precisely so the real
                # sample size and the discard count stop being invisible.
                "n_effective": skill.get("n_effective"),
                "unrecognized_grade_rows": skill.get("unrecognized_grade_rows"),
                "accuracy": skill.get("accuracy"),
            }

        rankable = [(n, f) for n, f in feeds.items() if f["verdict"] != "INSUFFICIENT_DATA"]
        ranked = [n for n, _ in sorted(rankable, key=lambda x: (x[1]["mcc"] if x[1]["mcc"] is not None else -9), reverse=True)]

        # best_feed is the MAXIMUM of len(FEEDS) MCCs, so under the null it clears p<0.05
        # roughly 1 - 0.95**len(FEEDS) of the time — about 23% at five feeds. It also used
        # to accept a feed whose own verdict was NO_DEMONSTRABLE_SKILL, so the winner of
        # five coin flips was announced as the best signal and recommended for wiring in.
        # Require the feed to have earned a verdict on its own, Bonferroni-corrected.
        best = None
        for name in ranked:
            f = feeds[name]
            if f.get("verdict") == "DIRECTIONAL_SKILL_CONFIRMED":
                best = name
                break

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "PER_FEED_SKILL",
            "horizon_hours": self.horizon_hours,
            "shadow_entries_raw": len(raw_entries),
            "shadow_entries_deduped": len(entries),
            "joined_with_price": len(moves),
            "feeds": feeds,
            "ranked_by_mcc": ranked,
            "best_feed": best,
            # best_feed can now be None even when `ranked` is non-empty, because a feed
            # must earn DIRECTIONAL_SKILL_CONFIRMED to be named rather than merely topping
            # the list. Indexing feeds[best] on that path raised KeyError(None) and took
            # the whole /feature-skill route down — caught by test_route_audit.
            "interpretation": (
                "Not enough joined data yet — let the session accumulate."
                if not ranked else
                (f"'{best}' has the highest directional MCC ({feeds[best]['mcc']}) AND "
                 "earned a significant verdict — a candidate to wire into the live decision."
                 if best else
                 f"No feed demonstrated skill. Top of the ranking is '{ranked[0]}' "
                 f"(MCC {feeds[ranked[0]]['mcc']}), but it did not earn a significant "
                 "verdict, so it is the best of several coin flips rather than a signal. "
                 "best_feed is deliberately null.")
            ),
            "status": "PER_FEED_SKILL_READY",
        }
