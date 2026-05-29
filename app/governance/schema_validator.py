class SchemaValidator:

    REQUIRED_TRADE_FIELDS = [
        "trade_id",
        "symbol",
        "state",
        "origin",
        "entry_price",
        "quantity",
        "confidence"
    ]

    def validate_trade(self, trade):

        missing_fields = []

        for field in self.REQUIRED_TRADE_FIELDS:
            if field not in trade:
                missing_fields.append(field)

        return {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields
        }

    def validate_ledger(self, ledger):

        results = []

        for trade in ledger.get("trades", []):
            results.append(
                self.validate_trade(trade)
            )

        return {
            "records_checked": len(results),
            "results": results
        }