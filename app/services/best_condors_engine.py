"""The ranked list of buildable iron condors — VRP + earnings, built off Unusual Whales.

Now that condors are constructed from UW's clean greeks + NBBO (not the SIM sandbox's garbage quotes),
both condor sleeves produce real, defined-risk, positive-credit condors. This engine gathers them into
one ranked list (richest return-on-risk first) for the dashboard.

PATTERN: the SCHEDULER recomputes + caches to a file (the plans make UW calls and take seconds); the
ROUTE only ever READS the cache, so the dashboard card is always instant and never hammers UW.
"""

import json
import time
from datetime import datetime, date
from pathlib import Path

CACHE = Path("app/data/condor_shadow/best_condors.json")


class BestCondorsEngine:

    TTL_SECONDS = 600            # scheduler recomputes at most once / 10 min

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _fmt(self, con, sleeve):
        legs = con.get("legs") or {}

        def k(name):
            return (legs.get(name) or {}).get("strike")
        # DTE is computed from `expiration` (the condor dicts carry no `entry_dte` — reading that key
        # left the card's days-to-expiry blank on EVERY row, the same silent key-mismatch class as the
        # earnings dry-run shape bug).
        exp = con.get("expiration")
        dte = None
        if exp:
            try:
                dte = (date.fromisoformat(str(exp)[:10]) - date.today()).days
            except Exception:
                dte = None
        return {
            "symbol": con.get("symbol"), "sleeve": sleeve, "expiration": exp,
            "dte": dte, "iv_rank": self._f(con.get("iv_rank")),
            "quantity": int(con.get("quantity") or 1),
            "max_gain_usd": round(self._f(con.get("credit_total")) or 0, 2),
            "max_loss_usd": round(self._f(con.get("max_loss_total")) or 0, 2),
            "return_on_risk": self._f(con.get("return_on_risk")),
            "short_put": k("short_put"), "wing_put": k("wing_put"),
            "short_call": k("short_call"), "wing_call": k("wing_call"),
        }

    def _gather(self):
        # errors are SURFACED (not silently swallowed): a sleeve that throws would otherwise vanish from
        # the card with no trace — the same silent-drop class we just fixed elsewhere.
        rows, errors = [], {}
        try:
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
            for con in (ConditionalVRPShortPremiumEngine().plan().get("planned") or []):
                rows.append(self._fmt(con, "VRP"))
        except Exception as e:
            errors["VRP"] = repr(e)[:160]
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            r = EarningsVolHarvestEngine().open_positions(dry_run=True)
            for con in (r.get("planned") if isinstance(r.get("planned"), list) else []) or []:
                rows.append(self._fmt(con, "Earnings"))
        except Exception as e:
            errors["Earnings"] = repr(e)[:160]
        rows.sort(key=lambda x: (x.get("return_on_risk") or -9), reverse=True)   # best risk-adjusted first
        return rows, errors

    # ---- compute (scheduler) -------------------------------------------------------------------
    def recompute(self):
        rows, errors = self._gather()
        data = {
            "timestamp": datetime.utcnow().isoformat(), "computed_epoch": time.time(),
            "count": len(rows), "condors": rows, "source": "UNUSUAL_WHALES",
            "sleeve_errors": errors,
            "note": ("Defined-risk iron condors VRP + earnings would sell, built off Unusual Whales "
                     "greeks + NBBO, ranked by return-on-risk. Max gain = net credit; max loss defined + capped."),
            "status": "BEST_CONDORS_DEGRADED" if errors else "BEST_CONDORS_READY",
        }
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data))
        except Exception:
            pass
        return data

    def recompute_if_due(self):
        """Scheduler entry: recompute only when the cache is missing or older than the TTL."""
        try:
            prev = json.loads(CACHE.read_text())
            if (time.time() - float(prev.get("computed_epoch") or 0)) < self.TTL_SECONDS:
                return {"status": "BEST_CONDORS_FRESH", "ran": False, "count": prev.get("count")}
        except Exception:
            pass
        d = self.recompute()
        return {"status": "BEST_CONDORS_RECOMPUTED", "ran": True, "count": d.get("count")}

    # ---- read (route) --------------------------------------------------------------------------
    def cached(self, limit=12):
        try:
            d = json.loads(CACHE.read_text())
            age = round(time.time() - float(d.get("computed_epoch") or 0))
            return {**d, "condors": (d.get("condors") or [])[:limit], "cache_age_seconds": age}
        except Exception:
            return {"timestamp": datetime.utcnow().isoformat(), "count": 0, "condors": [],
                    "status": "BEST_CONDORS_WARMING",
                    "note": "computing the first condor scan off Unusual Whales — refresh shortly"}
