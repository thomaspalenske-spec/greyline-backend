from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.skill_metrics_engine import SkillMetricsEngine

BULLISH = "BULLISH"
BEARISH = "BEARISH"


class FlowSkillValidationEngine:
    """
    THE test of GreyLine's founding hypothesis: does the real institutional-flow signal
    (Unusual Whales buying vs selling) predict forward direction?

    For each recorded flow snapshot (institutional_memory/<SYM>.jsonl), the flow-implied
    direction is BULLISH if institutional_buying_score > selling_score, else BEARISH. That
    is graded against the actual move over a fixed horizon (prices joined from the decision
    ledger + PriceHistoryStore), then scored with the drift-robust MCC metric.

    Honest by construction: reports data-quality gates (no API key, constant/degenerate
    flow signal, insufficient joined sample) so it never fakes a verdict on absent data.
    """

    def __init__(self, horizon_hours=24, tolerance_hours=6, band_pct=1.0):
        self.horizon_hours = float(horizon_hours)
        self.tolerance_hours = float(tolerance_hours)
        self.band_pct = float(band_pct)
        self.memory_dir = Path("app/data/institutional_memory")
        self.ledger = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.store = PriceHistoryStore()

    def _price_index(self, symbols):
        idx = {}
        for d in read_jsonl(self.ledger):
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

    def validate(self):
        key_configured = bool(getenv("UNUSUAL_WHALES_API_KEY"))
        snapshots = []
        for path in sorted(self.memory_dir.glob("*.jsonl")) if self.memory_dir.exists() else []:
            for row in read_jsonl(path):
                snap = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
                snapshots.append({
                    "symbol": snap.get("symbol") or row.get("symbol"),
                    "ts": row.get("timestamp"),
                    "buying": snap.get("institutional_buying_score"),
                    "selling": snap.get("institutional_selling_score"),
                })

        symbols = {str(s["symbol"]).upper() for s in snapshots if s["symbol"]}
        idx = self._price_index(symbols)
        horizon = timedelta(hours=self.horizon_hours)

        graded = []
        degenerate = 0  # buying == selling (no directional info)
        no_price = 0
        preds = set()
        for s in snapshots:
            b, sell = s["buying"], s["selling"]
            ts = _parse(s["ts"])
            if not isinstance(b, (int, float)) or not isinstance(sell, (int, float)) or b == sell or ts is None:
                degenerate += 1
                continue
            predicted = BULLISH if b > sell else BEARISH
            preds.add(predicted)
            cur = self._price_at(idx, s["symbol"], ts)
            fwd = self._price_at(idx, s["symbol"], ts + horizon)
            if not cur or not fwd:
                no_price += 1
                continue
            raw = (fwd / cur - 1) * 100
            directional = raw if predicted == BULLISH else -raw
            grade = "FAVORABLE" if directional >= self.band_pct else "UNFAVORABLE" if directional <= -self.band_pct else "NEUTRAL"
            graded.append({"directional_bias": predicted, "grade": grade})

        skill = SkillMetricsEngine().evaluate(graded)

        data_quality = []
        if not key_configured:
            data_quality.append("UNUSUAL_WHALES_API_KEY_NOT_CONFIGURED (flow signal cannot populate)")
        if len(preds) < 2:
            data_quality.append("FLOW_SIGNAL_CONSTANT_OR_ONE_SIDED (buying/selling not varying — likely defaulted)")
        if not graded:
            data_quality.append("NO_JOINED_FLOW+PRICE_SAMPLE_YET (accumulate data, then re-run)")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "FLOW_SKILL_VALIDATION",
            "hypothesis": "institutional buying>selling predicts forward direction",
            "horizon_hours": self.horizon_hours,
            "flow_snapshots_seen": len(snapshots),
            "usable_graded": len(graded),
            "degenerate_or_equal_signal": degenerate,
            "dropped_no_price_join": no_price,
            "unusual_whales_key_configured": key_configured,
            "data_quality_warnings": data_quality,
            "skill": skill,
            "status": "FLOW_SKILL_VALIDATION_READY",
        }
