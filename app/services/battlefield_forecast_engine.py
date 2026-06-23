from datetime import datetime


class BattlefieldForecastEngine:

    def forecast(self, battlefield):

        health = battlefield.get("battlefield_health", "RED")

        best_call = battlefield.get("best_call", {}) or {}
        best_put = battlefield.get("best_put", {}) or {}

        call_score = float(best_call.get("score", 0))
        put_score = float(best_put.get("score", 0))

        strongest_score = max(call_score, put_score)

        if strongest_score >= 90:
            green = 55
            yellow = 35
            red = 10

        elif strongest_score >= 85:
            green = 35
            yellow = 45
            red = 20

        elif strongest_score >= 80:
            green = 15
            yellow = 50
            red = 35

        else:
            green = 5
            yellow = 25
            red = 70

        expected_state = max(
            [
                ("GREEN", green),
                ("YELLOW", yellow),
                ("RED", red),
            ],
            key=lambda x: x[1],
        )[0]

        drivers = []

        if call_score > 80:
            drivers.append("Bullish setup approaching readiness")

        if put_score > 80:
            drivers.append("Bearish setup approaching readiness")

        if not drivers:
            drivers.append("No directional setup near readiness")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldForecastEngine",
            "current_battlefield_health": health,
            "forecast_24h": {
                "red": red,
                "yellow": yellow,
                "green": green,
            },
            "expected_state": expected_state,
            "forecast_drivers": drivers,
            "status": "BATTLEFIELD_FORECAST_READY",
        }
