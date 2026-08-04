"""Unusual Whales as the option-chain source for condor construction.

The TradeStation SIM sandbox streams only a narrow, garbage-quoted strike band (a $1-fair wing
quoted at $4, adjacent strikes priced 4-7x apart), so build_condor could never form a positive-credit
defined-risk condor on it. UW publishes clean, real-market data via two endpoints, joined on the OCC
option symbol:
  * /api/stock/{ticker}/greeks           -> per-strike call/put DELTA, IV, vega + the OCC symbols
  * /api/stock/{ticker}/option-contracts -> per-contract NBBO bid/ask + open interest
This engine joins them into the SAME contract shape build_condor already consumes (Side / Legs[Symbol]
/ Bid / Ask / Delta / ImpliedVolatility / Vega / DailyOpenInterest), keeps only TWO-SIDED quotes, and
prefers liquid MONTHLY expiries (the AdaptiveDTE weekly it used before had ~0 two-sided quotes even on
SPY). Verified 2026-07-30: IWM 25d put / 15d call land on exact target deltas with 2-5c spreads.

Drop-in for TradeStationOptionChainLiveEngine.get_chain_snapshot(). Gated by the UW key.
"""

import re
import time as _time
from datetime import date, timedelta
from os import getenv


class UWOptionChainEngine:

    _cache = {}
    CACHE_TTL_SECONDS = 30
    _OCC = re.compile(r"^([A-Z.]+)(\d{6})([CP])(\d{8})$")

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        # Resolve the key the SAME way the provider does (.env + .env.local) so the gate can't read False
        # while the provider works — which silently dropped the condor build to the slow TS SIM fallback.
        from app.services.env_reload import uw_api_key
        return bool(uw_api_key())

    # ---- OCC ("IWM260918C00313000") -> TradeStation-style ("IWM 260918C313") --------------------
    @classmethod
    def _occ_to_ts(cls, occ):
        m = cls._OCC.match(str(occ or "").upper().strip())
        if not m:
            return None
        ticker, yymmdd, cp, k8 = m.groups()
        strike = int(k8) / 1000.0
        ks = str(int(strike)) if strike == int(strike) else ("%.3f" % strike).rstrip("0").rstrip(".")
        return f"{ticker} {yymmdd}{cp}{ks}"

    # ---- liquid MONTHLY expiry nearest the target DTE (3rd Friday) ------------------------------
    @staticmethod
    def _third_friday(y, m):
        d = date(y, m, 1)
        first_fri = d + timedelta(days=(4 - d.weekday()) % 7)   # Mon=0 .. Fri=4
        return first_fri + timedelta(days=14)

    @classmethod
    def monthly_expiry(cls, target_dte=42, band=(28, 56)):
        """The standard monthly (3rd-Friday) expiration nearest target_dte, preferring within-band."""
        today = date.today()
        cands = []
        for i in range(0, 6):
            m0 = today.month - 1 + i
            y, m = today.year + m0 // 12, m0 % 12 + 1
            tf = cls._third_friday(y, m)
            dte = (tf - today).days
            if dte >= 1:
                cands.append((abs(dte - target_dte), tf.isoformat(), dte))
        in_band = [c for c in cands if band[0] <= c[2] <= band[1]]
        pool = sorted(in_band or cands)
        return pool[0][1] if pool else None

    # ---- the join ------------------------------------------------------------------------------
    def _fetch(self, ticker, expiry_iso):
        from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
        p = UnusualWhalesProvider()
        greeks = (p._get(f"/api/stock/{ticker}/greeks", params={"expiry": expiry_iso}) or {}).get("data") or []
        oc = (p._get(f"/api/stock/{ticker}/option-contracts", params={"expiry": expiry_iso}) or {}).get("data") or []
        return greeks, oc

    def get_chain_snapshot(self, symbol, expiration, option_type="All", **kwargs):
        """Return {'contracts': [...]} in build_condor's format. `expiration` is an ISO date."""
        ticker = str(symbol).upper().strip()
        key = (ticker, str(expiration))
        hit = self._cache.get(key)
        now = _time.time()
        if hit and (now - hit[0]) < self.CACHE_TTL_SECONDS:
            return hit[1]
        try:
            greeks, oc = self._fetch(ticker, str(expiration))
        except Exception as e:
            return {"symbol": ticker, "expiration": expiration, "contracts": [], "source": "UNUSUAL_WHALES",
                    "status": "UW_CHAIN_ERROR", "error": str(e)[:120]}

        by_sym = {str(r.get("option_symbol")): r for r in oc}
        contracts = []
        sides = [("Call", "call_delta", "call_volatility", "call_vega", "call_option_symbol"),
                 ("Put", "put_delta", "put_volatility", "put_vega", "put_option_symbol")]
        for row in greeks:
            for side, dk, ivk, vk, symk in sides:
                occ = row.get(symk)
                ocrow = by_sym.get(str(occ))
                if not ocrow:
                    continue
                bid, ask = self._f(ocrow.get("nbbo_bid")), self._f(ocrow.get("nbbo_ask"))
                if bid <= 0 or ask <= 0:                    # TWO-SIDED quotes only
                    continue
                ts = self._occ_to_ts(occ)
                if not ts:
                    continue
                contracts.append({
                    "Side": side,
                    "Legs": [{"Symbol": ts}],
                    "Bid": bid, "Ask": ask,
                    "Delta": self._f(row.get(dk)),
                    "ImpliedVolatility": self._f(row.get(ivk)),
                    "Vega": self._f(row.get(vk)),
                    "DailyOpenInterest": int(self._f(ocrow.get("open_interest"))),
                })
        result = {"symbol": ticker, "expiration": expiration, "source": "UNUSUAL_WHALES",
                  "contracts_returned": len(contracts), "contracts": contracts,
                  "status": "UW_CHAIN_READY" if contracts else "UW_CHAIN_EMPTY"}
        self._cache[key] = (now, result)
        return result
