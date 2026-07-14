from datetime import datetime, timedelta
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.skill_metrics_engine import SkillMetricsEngine
from app.services.validation_dedup import dedupe_by_symbol_time


class ShadowComparisonEngine:
    """
    Head-to-head A/B: grades the live momentum-proxy direction and the flow-implied
    direction (both shadow-logged per decision) against actual forward moves at a fixed
    horizon, and reports each one's drift-robust MCC — so you can see, on the same trades,
    whether real institutional flow predicts better than the current momentum signal.
    """

    def __init__(self, horizon_hours=24, tolerance_hours=6, band_pct=1.0):
        self.horizon_hours = float(horizon_hours)
        self.tolerance_hours = float(tolerance_hours)
        self.band_pct = float(band_pct)
        self.ledger = Path("app/data/decision_shadow/decision_shadow_log.jsonl")
        self.price_ledger = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.store = PriceHistoryStore()

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

    def _price_at(self, idx, symbol, target_dt):
        pts = idx.get(str(symbol).upper())
        if not pts:
            return None
        best = min(pts, key=lambda p: abs((p[0] - target_dt).total_seconds()))
        if abs((best[0] - target_dt).total_seconds()) > self.tolerance_hours * 3600:
            return None
        return best[1]

    def _grade(self, direction, raw):
        if direction not in ("BULLISH", "BEARISH"):
            return None
        directional = raw if direction == "BULLISH" else -raw
        if directional >= self.band_pct:
            return "FAVORABLE"
        if directional <= -self.band_pct:
            return "UNFAVORABLE"
        return "NEUTRAL"

    def compare(self):
        raw_entries = read_jsonl(self.ledger)
        entries = dedupe_by_symbol_time(raw_entries)  # independent obs (1 per symbol/minute)
        symbols = {str(e.get("symbol")).upper() for e in entries if e.get("symbol")}
        idx = self._price_index(symbols)
        horizon = timedelta(hours=self.horizon_hours)

        momentum_graded, flow_graded = [], []
        joined = 0
        for e in entries:
            ts = _parse(e.get("timestamp"))
            if ts is None:
                continue
            cur = self._price_at(idx, e.get("symbol"), ts)
            fwd = self._price_at(idx, e.get("symbol"), ts + horizon)
            if not cur or not fwd:
                continue
            joined += 1
            raw = (fwd / cur - 1) * 100
            mg = self._grade(e.get("momentum_direction"), raw)
            fg = self._grade(e.get("flow_direction"), raw)
            if mg:
                momentum_graded.append({"directional_bias": e["momentum_direction"], "grade": mg})
            if fg:
                flow_graded.append({"directional_bias": e["flow_direction"], "grade": fg})

        momentum_skill = SkillMetricsEngine().evaluate(momentum_graded)
        flow_skill = SkillMetricsEngine().evaluate(flow_graded)

        m_mcc = momentum_skill.get("mcc")
        f_mcc = flow_skill.get("mcc")
        winner = None
        if momentum_skill["verdict"] != "INSUFFICIENT_DATA" and flow_skill["verdict"] != "INSUFFICIENT_DATA":
            if f_mcc > m_mcc:
                winner = "FLOW"
            elif m_mcc > f_mcc:
                winner = "MOMENTUM"
            else:
                winner = "TIE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "SHADOW_COMPARISON",
            "horizon_hours": self.horizon_hours,
            "shadow_entries_raw": len(raw_entries),
            "shadow_entries_deduped": len(entries),
            "joined_with_price": joined,
            "momentum_proxy": {"mcc": m_mcc, "verdict": momentum_skill["verdict"], "confusion_matrix": momentum_skill["confusion_matrix"]},
            "institutional_flow": {"mcc": f_mcc, "verdict": flow_skill["verdict"], "confusion_matrix": flow_skill["confusion_matrix"]},
            "winner": winner,
            "interpretation": (
                "Not enough joined data yet — let the session accumulate."
                if winner is None else
                f"{winner} has the higher directional MCC on the same decisions."
            ),
            "status": "SHADOW_COMPARISON_READY",
        }
