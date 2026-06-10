class ExecutionRequestValidatorEngine:

    VALID_ORDER_TYPES = {
        "BUY",
        "SELL",
        "BUY_TO_OPEN",
        "SELL_TO_CLOSE"
    }

    def validate(
        self,
        symbol,
        quantity,
        order_type
    ):
        errors = []

        if not symbol:
            errors.append("MISSING_SYMBOL")

        if quantity is None or quantity <= 0:
            errors.append("INVALID_QUANTITY")

        if order_type not in self.VALID_ORDER_TYPES:
            errors.append("INVALID_ORDER_TYPE")

        return {
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "valid": len(errors) == 0,
            "errors": errors,
            "execution_allowed": False,
            "order_placement_allowed": False,
            "status":
                "EXECUTION_REQUEST_VALID"
                if len(errors) == 0
                else "EXECUTION_REQUEST_INVALID"
        }
