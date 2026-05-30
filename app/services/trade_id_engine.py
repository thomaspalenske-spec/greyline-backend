from datetime import datetime


class TradeIdEngine:

    def generate_trade_id(self, existing_trades):

        today = datetime.utcnow().strftime("%Y%m%d")

        sequence = len(existing_trades) + 1

        return f"GL-{today}-{sequence:06d}"