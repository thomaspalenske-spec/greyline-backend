class SchemaValidator:

    REQUIRED_FIELDS = [
        "symbol",
        "quantity",
        "entry_price",
        "state"
    ]

    VALID_STATES = [
        "ACTIVE",
        "CLOSED"
    ]

    def validate_trade(self, trade):

        for field in self.REQUIRED_FIELDS:
            if field not in trade:
                return {
                    "valid": False,
                    "error": f"Missing field: {field}"
                }

        if trade["quantity"] <= 0:
            return {
                "valid": False,
                "error": "Quantity must be greater than zero"
            }

        if trade["entry_price"] <= 0:
            return {
                "valid": False,
                "error": "Entry price must be greater than zero"
            }

        if trade["state"] not in self.VALID_STATES:
            return {
                "valid": False,
                "error": "Invalid trade state"
            }

        return {
            "valid": True,
            "error": None
        }
