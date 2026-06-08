from datetime import datetime

from app.services.decision_replay_engine import DecisionReplayEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class ForwardOutcomeCaptureEngine:

    def capture(self, limit=50):
        replay = DecisionReplayEngine().replay_recent_decisions(limit=limit)
        decisions = replay.get("replayed_decisions", [])

        captures = []
        captured_count = 0
        skipped_count = 0

        for item in decisions:
            symbol = item.get("symbol")

            if not symbol:
                skipped_count += 1
                captures.append({
                    "decision_timestamp": item.get("original_timestamp"),
                    "decision": item.get("decision"),
                    "symbol": None,
                    "capture_status": "SKIPPED_NO_SYMBOL",
                    "capture_reason": "Decision event has no symbol attached",
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })
                continue

            try:
                quote = TradeStationQuoteLiveEngine().get_quote(symbol)
                captured_count += 1

                quote_row = {}
                response_json = quote.get("response_json") or {}
                quotes = response_json.get("Quotes") or []
                if quotes:
                    quote_row = quotes[0]

                captures.append({
                    "decision_timestamp": item.get("original_timestamp"),
                    "capture_timestamp": datetime.utcnow().isoformat(),
                    "decision": item.get("decision"),
                    "symbol": symbol,
                    "replay_state": item.get("replay_state"),
                    "quote_status": quote.get("status"),
                    "http_status": quote.get("http_status"),
                    "last": quote_row.get("Last"),
                    "bid": quote_row.get("Bid"),
                    "ask": quote_row.get("Ask"),
                    "previous_close": quote_row.get("PreviousClose"),
                    "volume": quote_row.get("Volume"),
                    "trade_time": quote_row.get("TradeTime"),
                    "capture_status": "FORWARD_OUTCOME_CAPTURED",
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })

            except Exception as exc:
                skipped_count += 1
                captures.append({
                    "decision_timestamp": item.get("original_timestamp"),
                    "decision": item.get("decision"),
                    "symbol": symbol,
                    "capture_status": "CAPTURE_FAILED",
                    "capture_reason": str(exc),
                    "execution_enabled": False,
                    "order_placement_allowed": False,
                })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "FORWARD_OUTCOME_CAPTURE",
            "events_analyzed": len(decisions),
            "captured_count": captured_count,
            "skipped_count": skipped_count,
            "captures": captures,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "FORWARD_OUTCOME_CAPTURE_READY",
        }
