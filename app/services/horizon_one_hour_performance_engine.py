import json
from app.services.time_utils import parse_utc
from datetime import datetime, timedelta
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


from app.services.price_history_store import PriceHistoryStore


class HorizonOneHourPerformanceEngine:
    def __init__(self):
        self.file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.price_store = PriceHistoryStore()

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return parse_utc(value)
        except Exception:
            return None

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            return float(row.get("Last") or 0)
        except Exception:
            return 0.0

    def evaluate(self, limit=500):
        if not self.file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "record_count": 0,
                "status": "NO_HORIZON_DATA",
            }

        rows = [json.loads(x) for x in self.file.read_text().splitlines()[-limit:] if x.strip()]
        now = datetime.utcnow()

        prices = {}
        scored = []
        malformed = 0
        no_horizon_price = 0

        for r in rows:
            ts = self._parse_dt(r.get("timestamp"))
            if not ts:
                continue

            age_hours = round((now - ts).total_seconds() / 3600, 2)
            if age_hours < 1:
                continue

            symbol = r.get("symbol")
            snapshot = float(r.get("snapshot_price") or 0)
            if not symbol or snapshot <= 0:
                malformed += 1
                continue

            # A ONE-HOUR horizon, as the class name promises.
            #
            # `age_hours >= 1` is only a floor on eligibility; every row was then scored
            # against the CURRENT price, so rows days old were measured over days while the
            # engine published accuracy_pct under the name "HorizonOneHourPerformance". No
            # one-hour measurement existed anywhere in the file. Read the price AT T+1h and
            # leave the row unscored if that price does not exist yet.
            hit = self.price_store.price_at(
                symbol, (ts + timedelta(hours=1)).isoformat(),
                max_tolerance_seconds=900, direction="after")
            if not hit:
                no_horizon_price += 1
                continue
            current = hit["price"]

            raw_return = round(((current - snapshot) / snapshot) * 100, 4)
            directional_return = raw_return
            if r.get("directional_bias") == "BEARISH":
                directional_return = round(-raw_return, 4)

            scored.append({
                "symbol": symbol,
                "directional_bias": r.get("directional_bias"),
                "candidate_result": r.get("result"),
                "snapshot_price": snapshot,
                "current_price": current,
                "age_hours": age_hours,
                "raw_return_pct": raw_return,
                "directional_return_pct": directional_return,
                "prediction_correct": directional_return > 0,
                "regime_score": r.get("regime_score"),
                "regime": r.get("regime"),
                "risk_state_score": r.get("risk_state_score"),
                "risk_state": r.get("risk_state"),
                "breadth_score": r.get("breadth_score"),
                "breadth_state": r.get("breadth_state"),
                "setup_score_context": r.get("setup_score_context"),
                "setup_state": r.get("setup_state"),
                "asymmetry_score": r.get("asymmetry_score"),
                "asymmetry_state": r.get("asymmetry_state"),
                "volatility_score": r.get("volatility_score"),
                "volatility_state": r.get("volatility_state"),
            })

        correct = len([x for x in scored if x.get("prediction_correct")])
        # Independence. The ledger re-logs the same symbols every scheduler cycle, so the
        # 500 rows this reads have been as few as 4 distinct symbols (QQQ 198, XLP 198,
        # IBIT 52, XLV 52), each compared against one shared quote — all rows for a symbol
        # resolve correct-or-incorrect together. "eligible_predictions: 500" alongside a
        # clean accuracy read as a decisively measured hit rate. It was four coin flips.
        effective_n = len({(x.get("symbol"), str(x.get("timestamp") or "")[:10]) for x in scored})
        # None, not 0: "no measurement" and "measured 0% accuracy / breakeven" were the
        # same output, and the file already has a NO_HORIZON_DATA path for the former.
        avg_return = (round(sum(x.get("directional_return_pct", 0) for x in scored) / len(scored), 4)
                      if scored else None)
        accuracy = round((correct / len(scored)) * 100, 2) if scored else None
        # Suppressed below the independent-sample minimum. 376 rows over 4 symbol-days is
        # 4 observations; publishing a clean percentage beside it invites the reader to
        # treat it as a measured hit rate.
        under_min = effective_n < 30
        if under_min:
            accuracy = None
            avg_return = None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HorizonOneHourPerformanceEngine",
            "eligible_predictions": len(scored),
            "effective_n_symbol_days": effective_n,
            # Rows silently vanished from the denominator on a quote outage, so "measured
            # 40" and "measured 40 of 500 because quotes failed" looked identical.
            "dropped_breakdown": {"malformed_record": malformed,
                                  "no_horizon_price_yet": no_horizon_price},
            "correct_predictions": correct,
            "accuracy_pct": accuracy,
            "suppressed_below_min_sample": under_min,
            "average_directional_return_pct": avg_return,
            "latest_scored": scored[-25:],
            "status": "HORIZON_ONE_HOUR_PERFORMANCE_READY",
        }
