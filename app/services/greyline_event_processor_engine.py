from datetime import datetime


class GreyLineEventProcessorEngine:

    def process_events(self, events, positions):

        updated_positions = []
        total_unrealized_pnl = 0

        for pos in positions:

            symbol = pos.get("symbol")
            entry_price = pos.get("entry_price", 0)
            quantity = pos.get("quantity", 0)

            latest_price = None

            for event in reversed(events):
                if event.get("symbol") == symbol:
                    latest_price = event.get("price")
                    break

            if latest_price is None:
                updated_positions.append(pos)
                continue

            pnl = (latest_price - entry_price) * quantity

            updated_positions.append({
                **pos,
                "current_price": latest_price,
                "unrealized_pnl": round(pnl, 2),
                "market_value": round(latest_price * quantity, 2)
            })

            total_unrealized_pnl += pnl

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "positions": updated_positions,
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "event_count": len(events),
            "status": "EVENT_PROCESSING_COMPLETE"
        }
