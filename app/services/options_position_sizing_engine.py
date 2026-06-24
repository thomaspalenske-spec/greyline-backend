class OptionsPositionSizingEngine:
    def evaluate(self, account_equity=10000, option_ask=0, max_position_pct=0.05):
        try:
            equity = float(account_equity or 10000)
            ask = float(option_ask or 0)
            max_pct = float(max_position_pct or 0.05)
        except Exception:
            equity, ask, max_pct = 10000.0, 0.0, 0.05

        max_position_dollars = equity * max_pct
        contract_cost = ask * 100

        if contract_cost <= 0:
            contracts = 0
        elif contract_cost > max_position_dollars:
            contracts = 0
        else:
            contracts = int(max_position_dollars // contract_cost)

        return {
            "account_equity": equity,
            "max_position_pct": max_pct,
            "max_position_dollars": round(max_position_dollars, 2),
            "option_ask": ask,
            "contract_cost": round(contract_cost, 2),
            "recommended_contracts": contracts,
            "sizing_action": "SKIP_CONTRACT_TOO_EXPENSIVE" if contracts == 0 and contract_cost > max_position_dollars else "APPROVED",
            "estimated_position_cost": round(contracts * contract_cost, 2),
            "status": "OPTIONS_POSITION_SIZE_READY",
        }
