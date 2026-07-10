from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.data_providers.unusual_whales_provider import (
    UnusualWhalesProvider,
)


class UnusualWhalesOperationalEnvironmentEngine:
    """
    Unified live Unusual Whales operational-environment model.

    This engine gathers and normalizes authorized direct feeds without
    modifying GreyLine execution decisions. Individual feed failures are
    isolated so one unavailable endpoint cannot break the full snapshot.
    """

    def __init__(self):
        try:
            self.uw = UnusualWhalesProvider()
        except Exception:
            self.uw = None

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _list_data(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]

        return []

    @staticmethod
    def _dict_data(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, dict):
                return data

        return {}

    def _safe_call(self, name, call):
        try:
            value = call()

            return {
                "available": value is not None,
                "value": value,
                "error": None,
            }
        except Exception as exc:
            return {
                "available": False,
                "value": None,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }

    def _premium_flow_summary(self, rows):
        call_premium = 0.0
        put_premium = 0.0
        ask_side_premium = 0.0
        bid_side_premium = 0.0

        for row in rows:
            option_type = str(
                row.get("option_type")
                or row.get("type")
                or ""
            ).lower()

            premium = self._float(
                row.get("premium")
                or row.get("total_premium")
            )

            tags = [
                str(tag).lower()
                for tag in (row.get("tags") or [])
            ]

            if option_type == "call" or "bullish" in tags:
                call_premium += premium
            elif option_type == "put" or "bearish" in tags:
                put_premium += premium

            ask_side_premium += self._float(
                row.get("total_ask_side_prem")
            )
            bid_side_premium += self._float(
                row.get("total_bid_side_prem")
            )

        net_premium = call_premium - put_premium
        total_directional = call_premium + put_premium

        directional_score = (
            (net_premium / total_directional) * 100
            if total_directional > 0
            else 0.0
        )

        return {
            "record_count": len(rows),
            "call_premium": round(call_premium, 2),
            "put_premium": round(put_premium, 2),
            "net_premium": round(net_premium, 2),
            "directional_score": round(directional_score, 2),
            "ask_side_premium": round(ask_side_premium, 2),
            "bid_side_premium": round(bid_side_premium, 2),
        }

    def _flow_distribution_summary(self, rows, key):
        call_premium = 0.0
        put_premium = 0.0
        concentrations = []

        for row in rows:
            row_call = self._float(row.get("call_premium"))
            row_put = self._float(row.get("put_premium"))
            total = row_call + row_put

            call_premium += row_call
            put_premium += row_put

            concentrations.append({
                key: row.get(key),
                "call_premium": round(row_call, 2),
                "put_premium": round(row_put, 2),
                "net_premium": round(row_call - row_put, 2),
                "total_premium": round(total, 2),
            })

        concentrations.sort(
            key=lambda row: row["total_premium"],
            reverse=True,
        )

        total_premium = call_premium + put_premium
        score = (
            ((call_premium - put_premium) / total_premium) * 100
            if total_premium > 0
            else 0.0
        )

        return {
            "record_count": len(rows),
            "call_premium": round(call_premium, 2),
            "put_premium": round(put_premium, 2),
            "net_premium": round(
                call_premium - put_premium,
                2,
            ),
            "directional_score": round(score, 2),
            "top_concentrations": concentrations[:10],
        }

    def _dark_pool_summary(self, rows):
        valid = [
            row for row in rows
            if not row.get("canceled")
        ]

        total_premium = sum(
            self._float(row.get("premium"))
            for row in valid
        )
        total_size = sum(
            self._float(row.get("size"))
            for row in valid
        )

        ranked = sorted(
            valid,
            key=lambda row: self._float(row.get("premium")),
            reverse=True,
        )

        return {
            "record_count": len(valid),
            "total_premium": round(total_premium, 2),
            "total_size": round(total_size, 2),
            "largest_prints": [
                {
                    "ticker": row.get("ticker"),
                    "price": self._float(row.get("price")),
                    "size": self._float(row.get("size")),
                    "premium": self._float(row.get("premium")),
                    "executed_at": row.get("executed_at"),
                    "market_center": row.get("market_center"),
                }
                for row in ranked[:10]
            ],
        }

    def _oi_change_summary(self, rows):
        positive = []
        negative = []

        for row in rows:
            change = self._float(
                row.get("oi_diff_plain")
                or row.get("oi_change")
            )

            item = {
                "option_symbol": row.get("option_symbol"),
                "oi_change": round(change, 2),
                "current_oi": self._float(row.get("curr_oi")),
                "previous_oi": self._float(row.get("last_oi")),
                "volume": self._float(row.get("volume")),
                "previous_total_premium": self._float(
                    row.get("prev_total_premium")
                ),
            }

            if change > 0:
                positive.append(item)
            elif change < 0:
                negative.append(item)

        positive.sort(
            key=lambda row: row["oi_change"],
            reverse=True,
        )
        negative.sort(
            key=lambda row: row["oi_change"],
        )

        return {
            "record_count": len(rows),
            "positive_oi_change_count": len(positive),
            "negative_oi_change_count": len(negative),
            "largest_oi_increases": positive[:10],
            "largest_oi_decreases": negative[:10],
        }

    def _oi_per_strike_summary(self, rows):
        concentrations = []

        total_call_oi = 0.0
        total_put_oi = 0.0

        for row in rows:
            call_oi = self._float(row.get("call_oi"))
            put_oi = self._float(row.get("put_oi"))

            total_call_oi += call_oi
            total_put_oi += put_oi

            concentrations.append({
                "strike": self._float(row.get("strike")),
                "call_oi": call_oi,
                "put_oi": put_oi,
                "total_oi": call_oi + put_oi,
                "net_call_minus_put_oi": call_oi - put_oi,
            })

        concentrations.sort(
            key=lambda row: row["total_oi"],
            reverse=True,
        )

        total_oi = total_call_oi + total_put_oi
        call_share = (
            total_call_oi / total_oi * 100
            if total_oi > 0
            else 0.0
        )

        return {
            "record_count": len(rows),
            "total_call_oi": round(total_call_oi, 2),
            "total_put_oi": round(total_put_oi, 2),
            "call_oi_share_pct": round(call_share, 2),
            "top_oi_strikes": concentrations[:10],
        }

    def _greek_exposure_summary(self, rows):
        if not rows:
            return {
                "record_count": 0,
                "latest": None,
            }

        latest = rows[-1]

        return {
            "record_count": len(rows),
            "latest": {
                "date": latest.get("date"),
                "call_gamma": self._float(
                    latest.get("call_gamma")
                ),
                "put_gamma": self._float(
                    latest.get("put_gamma")
                ),
                "net_gamma": round(
                    self._float(latest.get("call_gamma"))
                    + self._float(latest.get("put_gamma")),
                    4,
                ),
                "call_delta": self._float(
                    latest.get("call_delta")
                ),
                "put_delta": self._float(
                    latest.get("put_delta")
                ),
                "call_charm": self._float(
                    latest.get("call_charm")
                ),
                "put_charm": self._float(
                    latest.get("put_charm")
                ),
                "call_vanna": self._float(
                    latest.get("call_vanna")
                ),
                "put_vanna": self._float(
                    latest.get("put_vanna")
                ),
            },
        }

    def _vrp_summary(self, rows):
        if not rows:
            return {
                "record_count": 0,
                "latest": None,
            }

        latest = rows[-1]

        return {
            "record_count": len(rows),
            "latest": {
                "date": latest.get("date"),
                "risk_premium": self._float(
                    latest.get("risk_premium")
                ),
                "rank": self._float(latest.get("rank")),
            },
        }

    def analyze(self, symbol):
        symbol = (symbol or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        if not self.uw:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "direct_feed_connected": False,
                "status": "UNUSUAL_WHALES_OPERATIONAL_ENVIRONMENT_UNAVAILABLE",
            }

        calls = {
            "recent_flow": self._safe_call(
                "recent_flow",
                lambda: self.uw.recent_flow(symbol),
            ),
            "symbol_dark_pool": self._safe_call(
                "symbol_dark_pool",
                lambda: self.uw.dark_pool(symbol),
            ),
            "recent_dark_pool": self._safe_call(
                "recent_dark_pool",
                self.uw.recent_dark_pool,
            ),
            "flow_per_strike": self._safe_call(
                "flow_per_strike",
                lambda: self.uw.flow_per_strike(symbol),
            ),
            "flow_per_expiry": self._safe_call(
                "flow_per_expiry",
                lambda: self.uw.flow_per_expiry(symbol),
            ),
            "flow_alerts": self._safe_call(
                "flow_alerts",
                lambda: self.uw.flow_alerts(symbol),
            ),
            "net_flow": self._safe_call(
                "net_flow",
                self.uw.net_flow,
            ),
            "gex_levels": self._safe_call(
                "gex_levels",
                lambda: self.uw.gex_levels(symbol),
            ),
            "greek_exposure": self._safe_call(
                "greek_exposure",
                lambda: self.uw.greek_exposure(symbol),
            ),
            "oi_change": self._safe_call(
                "oi_change",
                lambda: self.uw.oi_change(symbol),
            ),
            "oi_per_strike": self._safe_call(
                "oi_per_strike",
                lambda: self.uw.oi_per_strike(symbol),
            ),
            "variance_risk_premium": self._safe_call(
                "variance_risk_premium",
                lambda: self.uw.variance_risk_premium(symbol),
            ),
        }

        available = [
            name for name, result in calls.items()
            if result.get("available")
        ]
        unavailable = [
            name for name, result in calls.items()
            if not result.get("available")
        ]

        recent_flow_rows = self._list_data(
            calls["recent_flow"]["value"]
        )
        symbol_dark_pool_rows = self._list_data(
            calls["symbol_dark_pool"]["value"]
        )
        recent_dark_pool_rows = self._list_data(
            calls["recent_dark_pool"]["value"]
        )
        strike_rows = self._list_data(
            calls["flow_per_strike"]["value"]
        )
        expiry_rows = self._list_data(
            calls["flow_per_expiry"]["value"]
        )
        alert_rows = self._list_data(
            calls["flow_alerts"]["value"]
        )
        greek_rows = self._list_data(
            calls["greek_exposure"]["value"]
        )
        oi_change_rows = self._list_data(
            calls["oi_change"]["value"]
        )
        oi_strike_rows = self._list_data(
            calls["oi_per_strike"]["value"]
        )
        vrp_rows = self._list_data(
            calls["variance_risk_premium"]["value"]
        )

        gex_levels = self._dict_data(
            calls["gex_levels"]["value"]
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "UnusualWhalesOperationalEnvironmentEngine",
            "symbol": symbol,
            "direct_feed_connected": bool(available),
            "authorized_component_count": len(available),
            "unavailable_component_count": len(unavailable),
            "available_components": available,
            "unavailable_components": unavailable,
            "options_flow": self._premium_flow_summary(
                recent_flow_rows
            ),
            "flow_alerts": self._premium_flow_summary(
                alert_rows
            ),
            "flow_by_strike": self._flow_distribution_summary(
                strike_rows,
                "strike",
            ),
            "flow_by_expiry": self._flow_distribution_summary(
                expiry_rows,
                "expiry",
            ),
            "symbol_dark_pool": self._dark_pool_summary(
                symbol_dark_pool_rows
            ),
            "market_recent_dark_pool": self._dark_pool_summary(
                recent_dark_pool_rows
            ),
            "gex_levels": {
                "call_wall": gex_levels.get("call_wall"),
                "put_wall": gex_levels.get("put_wall"),
                "gamma_flip": gex_levels.get("gamma_flip"),
                "gamma_magnet": gex_levels.get("gamma_magnet"),
            },
            "greek_exposure": self._greek_exposure_summary(
                greek_rows
            ),
            "open_interest_change": self._oi_change_summary(
                oi_change_rows
            ),
            "open_interest_by_strike":
                self._oi_per_strike_summary(
                    oi_strike_rows
                ),
            "variance_risk_premium": self._vrp_summary(
                vrp_rows
            ),
            "market_net_flow_raw":
                calls["net_flow"]["value"],
            "component_errors": {
                name: result.get("error")
                for name, result in calls.items()
                if result.get("error")
            },
            "scoring_integration_enabled": False,
            "execution_impact": "OBSERVATION_ONLY",
            "status":
                "UNUSUAL_WHALES_OPERATIONAL_ENVIRONMENT_READY",
        }
