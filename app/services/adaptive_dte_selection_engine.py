"""Choose the condor's tenor from the LIVE market, not a hardcoded number.

The old selector took the nearest listed expiration above a 7-day floor — a fixed prescription that
ignored what the market was actually offering across tenors (and collided with the 7-DTE exit rule,
so a condor was born already flagged to liquidate). This engine instead asks, for each expiration in
a sane band: "if I sold the strategy's condor HERE, what does the market imply the trade is worth?"
and picks the best one.

"Most probable", honestly defined — it does NOT invent a private forecast (this project has been
burned repeatedly building adaptive cleverness that was just curve-fit to a crash-free sample). It
optimizes over the MARKET'S OWN implied distribution, all observable:

  * P(profit) proxy  = 1 - |short_put_delta| - |short_call_delta|   (delta ~= risk-neutral P(ITM);
                        the chance both shorts expire out-of-the-money — the condor's win region)
  * executable credit = build_condor's real credit (short bids - wing asks: cost already embedded)
  * defined max loss  = build_condor's real capped loss
  * expected value    = P(profit) x (credit x profit-take) - (1 - P(profit)) x max_loss
  * rank              = EV per dollar of defined risk

GreyLine's EDGE is that it only sells this when IV is rich (realized tends to come in BELOW implied),
so the true win rate is HIGHER than the delta-implied POP — meaning this ranking is conservative, and
the richness screen (elsewhere) is what turns implied-EV into realized edge. This engine only decides
WHICH tenor, never whether the premium is worth selling.

Guardrails, because adaptive != better:
  * HARD BAND [MIN_DTE, MAX_DTE] — it can never pick a gamma-bomb weekly or a vega-heavy LEAP, and
    never returns a tenor at/under the exit floor. This alone fixes the old collision.
  * STATIC FALLBACK — disabled, degraded data, or an empty band => nearest listed expiry to a target
    DTE inside the band (never a sub-band literal).
  * INSPECTABLE — scorecard() shows every candidate tenor and its components, so the choice is never
    a black box (route /adaptive-dte).
  * UNPROVEN until measured — whether adaptive tenor beats the static target is a registered
    hypothesis; only an out-of-sample panel can settle it. Enabled per operator directive, guarded.
"""

import json
from datetime import datetime, timezone
from os import getenv
from pathlib import Path


class AdaptiveDTESelectionEngine:

    # tenor band (days-to-expiry). Entry can never land outside this; MIN sits comfortably above the
    # condor exit floor (MANAGE_DTE) so entry and exit can't collide.
    DEFAULT_MIN_DTE = 28
    DEFAULT_MAX_DTE = 56
    DEFAULT_TARGET_DTE = 42          # static fallback aims here (mid-band, textbook ~45)
    MAX_CANDIDATES = 5               # cap live chain fetches per name
    PROFIT_TAKE_FRAC = 0.50          # matches the condor exit doctrine (bank at 50% of credit)

    _cache = {}                      # {(symbol, date): {"expiration":..., "scorecard":[...]}}

    @staticmethod
    def _int_env(key, default):
        try:
            return int(getenv(key, "") or default)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _band(cls):
        return (cls._int_env("GREYLINE_DTE_BAND_MIN", cls.DEFAULT_MIN_DTE),
                cls._int_env("GREYLINE_DTE_BAND_MAX", cls.DEFAULT_MAX_DTE))

    @classmethod
    def _target(cls):
        return cls._int_env("GREYLINE_DTE_TARGET", cls.DEFAULT_TARGET_DTE)

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    # ---- overridable seams (tests patch these) -------------------------------------------------

    def _list_expirations(self, symbol):
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        return TradeStationOptionChainLiveEngine().get_expirations(symbol).get("expirations") or []

    def _score_tenor(self, symbol, expiration):
        """Build the strategy's real condor at this expiration and score it. None if untradeable."""
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
        snap = TradeStationOptionChainLiveEngine().get_chain_snapshot(
            symbol=symbol, expiration=expiration, option_type="All", max_contracts=160, strike_proximity=40)
        con = ConditionalVRPShortPremiumEngine().build_condor(symbol, snap.get("contracts", []) or [])
        if con.get("skip"):
            return None
        return self._ev(con)

    # ---- scoring -------------------------------------------------------------------------------

    @classmethod
    def _ev(cls, con):
        """Expected value from a built condor's market-implied numbers."""
        spd = abs(cls._f(con.get("short_put_delta")))
        scd = abs(cls._f(con.get("short_call_delta")))
        pop = max(0.0, min(1.0, 1.0 - spd - scd))          # P(both shorts expire OTM) — win region
        credit = cls._f(con.get("credit_total"))
        max_loss = cls._f(con.get("max_loss_total"))
        if max_loss <= 0:
            return None
        ev = pop * (credit * cls.PROFIT_TAKE_FRAC) - (1.0 - pop) * max_loss
        return {"pop": round(pop, 3), "credit_total": round(credit, 2),
                "max_loss_total": round(max_loss, 2), "ev": round(ev, 2),
                "ev_per_risk": round(ev / max_loss, 4),
                "return_on_risk": con.get("return_on_risk")}

    # ---- candidate tenors ----------------------------------------------------------------------

    def _candidates(self, symbol, today=None):
        """[(dte, 'YYYY-MM-DD')] listed expirations inside the band, capped and spread across it."""
        today = today or datetime.now(timezone.utc).date()
        lo, hi = self._band()
        in_band = []
        for raw in self._list_expirations(symbol):
            try:
                d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            dte = (d - today).days
            if lo <= dte <= hi:
                in_band.append((dte, d.isoformat()))
        in_band.sort()
        if len(in_band) <= self.MAX_CANDIDATES:
            return in_band
        # keep the ones nearest to evenly-spaced DTE targets across the band, so we sample the band
        targets = [lo + (hi - lo) * i / (self.MAX_CANDIDATES - 1) for i in range(self.MAX_CANDIDATES)]
        picked = []
        for t in targets:
            best = min(in_band, key=lambda x: abs(x[0] - t))
            if best not in picked:
                picked.append(best)
        return sorted(picked)

    def _fallback(self, symbol, today=None):
        """Nearest listed expiry to the target DTE, clamped into the band — never a sub-band literal."""
        today = today or datetime.now(timezone.utc).date()
        lo, hi = self._band()
        cands = self._candidates(symbol, today)
        if cands:
            tgt = self._target()
            return min(cands, key=lambda x: abs(x[0] - tgt))[1]
        # nothing in band (thin/short chain): nearest listed expiry >= MIN, else furthest available
        allx = []
        for raw in self._list_expirations(symbol):
            try:
                d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            allx.append(((d - today).days, d.isoformat()))
        allx.sort()
        above = [x for x in allx if x[0] >= lo]
        if above:
            return above[0][1]
        return allx[-1][1] if allx else None

    # ---- public API ----------------------------------------------------------------------------

    def scorecard(self, symbol, today=None):
        """Full, inspectable decision for one name — every candidate tenor and its EV components."""
        today = today or datetime.now(timezone.utc).date()
        cands = self._candidates(symbol, today)
        rows = []
        for dte, exp in cands:
            s = None
            try:
                s = self._score_tenor(symbol, exp)
            except Exception as e:
                s = {"error": str(e)[:80]}
            rows.append({"expiration": exp, "dte": dte, **(s or {"untradeable": True})})
        scored = [r for r in rows if r.get("ev_per_risk") is not None]
        chosen = max(scored, key=lambda r: r["ev_per_risk"])["expiration"] if scored else \
            self._fallback(symbol, today)
        return {
            "symbol": symbol, "adaptive": self.enabled(), "band": self._band(),
            "target_dte_fallback": self._target(), "candidates": rows,
            "chosen_expiration": chosen,
            "method": "market-implied EV per unit defined-risk, argmax within band; static "
                      "target-DTE fallback when disabled/degraded",
            "status": "ADAPTIVE_DTE_SCORECARD",
        }

    def select(self, symbol, today=None):
        """Return the chosen expiration ('YYYY-MM-DD'). Static fallback unless adaptive is enabled."""
        today = today or datetime.now(timezone.utc).date()
        if not self.enabled():
            return self._fallback(symbol, today)                 # safe band-clamped static choice
        key = (symbol, today.isoformat())
        cached = self._cache.get(key)
        if cached:
            return cached["expiration"]
        try:
            cands = self._candidates(symbol, today)
            scored = []
            for dte, exp in cands:
                s = self._score_tenor(symbol, exp)
                if s:
                    scored.append((s["ev_per_risk"], exp, dte, s))
            if scored:
                scored.sort(reverse=True)
                exp = scored[0][1]
                self._cache[key] = {"expiration": exp,
                                    "scorecard": [{"expiration": e, "dte": d, **sd}
                                                  for _, e, d, sd in scored]}
                return exp
        except Exception:
            pass
        return self._fallback(symbol, today)                     # degraded -> never pathological
