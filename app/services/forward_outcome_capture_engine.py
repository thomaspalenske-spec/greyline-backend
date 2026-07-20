import json
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.price_history_store import PriceHistoryStore


def _parse_ts(value):
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00").split("+")[0])
    except Exception:
        return None


class ForwardOutcomeCaptureEngine:
    # Matches FixedHorizonGraderEngine so the two agree on what an outcome means.
    DEFAULT_HORIZON_HOURS = 24.0

    def __init__(self, horizon_hours=None, tolerance_hours=None):
        self.ledger_file = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.price_store = PriceHistoryStore()
        self.horizon_hours = float(
            horizon_hours or getenv("GREYLINE_GRADING_HORIZON_HOURS", self.DEFAULT_HORIZON_HOURS))
        # Tolerance must stay BELOW the horizon: at tolerance >= horizon the accepted
        # window reaches back past the decision itself and an 'outcome' could predate it.
        self.tolerance_hours = float(
            tolerance_hours if tolerance_hours is not None else self.horizon_hours / 4)

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            price = float(row.get("Last") or 0)
        except Exception:
            price = 0.0

        return {
            "symbol": symbol,
            "price": price,
            "quote_status": quote_result.get("status"),
            "trade_time": row.get("TradeTime"),
            "is_delayed": bool((row.get("MarketFlags") or {}).get("IsDelayed")),
        }

    def capture(self, limit=25):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "records_checked": 0,
                "status": "NO_FORWARD_OUTCOME_LEDGER",
            }

        lines = self.ledger_file.read_text().splitlines()
        records = [json.loads(x) for x in lines[-limit:] if x.strip()]

        symbols = sorted(set(r.get("symbol") for r in records if r.get("symbol")))
        prices = {symbol: self._last_price(symbol) for symbol in symbols}

        # Feed the forward-price time series. Fixed-horizon grading needs a price near
        # T+horizon for each decision, which only exists if we record prices as the
        # market moves forward. These quotes were already fetched above, so recording
        # them here is free — and it is the fuel the FixedHorizonGraderEngine was missing
        # (nothing was writing live points, so it could only ever grade PENDING).
        recorded_points = 0
        for symbol, p in prices.items():
            if (p.get("price") or 0) > 0 and not p.get("is_delayed"):
                # Stamp the point with the quote's OWN trade time when the broker gives us
                # one. Recording it at grader-run time labelled the whole series with when
                # we happened to look, and every downstream price_at join inherited that
                # skew while looking authoritative.
                if self.price_store.record(symbol, p["price"], timestamp=p.get("trade_time")):
                    recorded_points += 1

        outcomes = []
        for r in records:
            symbol = r.get("symbol")
            price = prices.get(symbol, {})
            current_price = price.get("price") or 0

            snapshot_price = float(r.get("snapshot_price") or 0)
            directional_bias = r.get("directional_bias")

            raw_return_pct = None
            directional_return_pct = None
            successful = None
            outcome_price = None
            elapsed_hours = None

            # FIXED HORIZON, not "whatever price exists when the grader runs".
            #
            # This previously divided the CURRENT live quote by the snapshot price, so the
            # holding period was the wall-clock gap between the decision and this run —
            # 0 to 5 hours, different for every row, and all rows for one symbol scored
            # against a single shared quote. PriceHistoryStore's own docstring names that
            # confound as the thing "that made GreyLine's edge unmeasurable"; this path
            # had reintroduced it. A decision younger than the horizon is now PENDING
            # rather than being scored over a few minutes.
            decision_dt = _parse_ts(r.get("timestamp"))
            if decision_dt is None or snapshot_price <= 0:
                outcome_state = "PRICE_UNAVAILABLE"
            else:
                target = decision_dt + timedelta(hours=self.horizon_hours)
                hit = self.price_store.price_at(
                    symbol, target.isoformat(),
                    max_tolerance_seconds=int(self.tolerance_hours * 3600),
                    direction="after")
                if not hit:
                    outcome_state = "PENDING_HORIZON_NOT_REACHED"
                else:
                    outcome_price = hit["price"]
                    elapsed_hours = round(
                        (self.horizon_hours * 3600 + hit["age_seconds"]) / 3600, 3)
                    outcome_state = "PRICE_CAPTURED"
                    raw_return_pct = round(((outcome_price / snapshot_price) - 1) * 100, 4)

                    if directional_bias == "BULLISH":
                        directional_return_pct = raw_return_pct
                        successful = outcome_price > snapshot_price
                    elif directional_bias == "BEARISH":
                        directional_return_pct = round(raw_return_pct * -1, 4)
                        successful = outcome_price < snapshot_price

            outcomes.append({
                "timestamp": datetime.utcnow().isoformat(),
                "candidate_timestamp": r.get("timestamp"),
                "symbol": symbol,
                "option_type": r.get("option_type"),
                "directional_bias": directional_bias,
                "candidate_result": r.get("result"),
                "candidate_score": r.get("score"),
                "candidate_rank": r.get("rank"),
                "snapshot_price": snapshot_price,
                "current_price": current_price,          # live quote, for reference only
                "outcome_price": outcome_price,          # the T+horizon price actually scored
                "horizon_hours": self.horizon_hours,
                "realized_horizon_hours": elapsed_hours,
                "raw_return_pct": raw_return_pct,
                "directional_return_pct": directional_return_pct,
                "successful": successful,
                "quote_trade_time": price.get("trade_time"),
                "quote_is_delayed": price.get("is_delayed"),
                "outcome_state": outcome_state,
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeCaptureEngine",
            "records_checked": len(records),
            "symbols_checked": symbols,
            "price_points_recorded": recorded_points,
            # Independence, surfaced. The scored rows are NOT independent samples: the
            # scheduler re-logs the same symbols every cycle, so 50 rows have been as few
            # as 2 symbols across 5 hours. Anything computing a win rate must divide by
            # these, not by len(outcomes).
            "distinct_symbols": len(symbols),
            "distinct_decision_days": len({
                str(r.get("timestamp") or "")[:10] for r in records if r.get("timestamp")}),
            "scored_count": sum(1 for o in outcomes if o["outcome_state"] == "PRICE_CAPTURED"),
            "pending_horizon_count": sum(
                1 for o in outcomes if o["outcome_state"] == "PENDING_HORIZON_NOT_REACHED"),
            "outcomes": outcomes,
            "status": "FORWARD_OUTCOME_CAPTURE_READY",
        }
