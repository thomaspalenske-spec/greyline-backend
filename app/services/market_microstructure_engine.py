from datetime import datetime

from app.services.order_book_pressure_engine import OrderBookPressureEngine
from app.services.bid_ask_imbalance_engine import BidAskImbalanceEngine
from app.services.absorption_detection_engine import AbsorptionDetectionEngine
from app.services.liquidity_sweep_engine import LiquiditySweepEngine
from app.services.iceberg_detection_engine import IcebergDetectionEngine


class MarketMicrostructureEngine:
    def evaluate(self, quote=None, tape=None):
        quote = quote or {}
        tape = tape or {}

        order_book = OrderBookPressureEngine().evaluate(quote)
        imbalance = BidAskImbalanceEngine().evaluate(quote)
        absorption = AbsorptionDetectionEngine().evaluate(quote, tape)
        sweep = LiquiditySweepEngine().evaluate(tape)
        iceberg = IcebergDetectionEngine().evaluate(tape)

        score = (
            order_book.get("score", 0) * 0.20
            + imbalance.get("score", 0) * 0.15
            + absorption.get("score", 0) * 0.30
            + sweep.get("score", 0) * 0.20
            + iceberg.get("score", 0) * 0.15
        )

        state = "BALANCED"
        if score >= 80:
            state = "INSTITUTIONAL_ACCUMULATION"
        elif score >= 65:
            state = "BUY_SIDE_PRESSURE"
        elif score <= 25:
            state = "INSTITUTIONAL_DISTRIBUTION"
        elif score <= 40:
            state = "SELL_SIDE_PRESSURE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "MarketMicrostructureEngine",
            "microstructure_score": round(score, 2),
            "microstructure_state": state,
            "order_book": order_book,
            "bid_ask_imbalance": imbalance,
            "absorption": absorption,
            "liquidity_sweep": sweep,
            "iceberg": iceberg,
            "data_mode": "PROXY_OR_LEVEL_TWO_READY",
            "status": "MARKET_MICROSTRUCTURE_READY",
        }
