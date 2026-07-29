"""Manage the book's GREEKS — the line between selling options and running a vol desk.

An elite options operation does not think in positions; it thinks in the aggregate greeks of the
whole book: net delta (directional exposure), net vega (the actual size of the vol bet), net gamma
(acceleration risk near expiry), net theta (the income being collected). GreyLine sold condors with
no view of any of this — and the put-tilt quietly makes the book NET LONG DELTA, so in a selloff it
loses on volatility (short vega) AND on direction (long delta) at once. That is an accidental
directional bet riding on top of what is supposed to be a pure premium harvest.

This engine computes the live aggregate greeks from the open positions (greeks per contract come
from the option chain), and — the point — reports the DELTA-NEUTRAL HEDGE: the number of underlying
shares to trade so the book's P&L is a clean vol/theta harvest, not contaminated by an unintended
directional view. Hedging itself places a real equity order, so it is DEFAULT OFF; by default this
reports the book greeks and the hedge the desk *should* do.

Sign convention: a leg's greek contribution = contract_greek x quantity x 100 x (+1 long / -1 short).
A short put is LONG delta (short a negative-delta option), which is exactly why the put-tilt tilts
the book long — visible here for the first time.
"""

import re
from datetime import datetime
from os import getenv
from pathlib import Path
import json


class PortfolioGreeksEngine:

    VRP_LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
    OPT_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
    _SYM = re.compile(r"^([A-Z.]+)\s+(\d{2})(\d{2})(\d{2})([CP])(\d+(?:\.\d+)?)$")
    DELTA_NEUTRAL_TOLERANCE_SHARES = 5    # book is "neutral enough" within this many delta-shares

    @staticmethod
    def _hedge_enabled():
        return (getenv("GREYLINE_GREEKS_DELTA_HEDGE", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _parse(cls, sym):
        """'SPY 260828C640' -> (underlying, 'YYYY-MM-DD')."""
        m = cls._SYM.match(str(sym or "").upper().strip())
        if not m:
            return None, None
        return m.group(1), f"20{m.group(2)}-{m.group(3)}-{m.group(4)}"

    def _open_legs(self):
        """Signed legs across the open books: [(symbol, qty, sign)] (+1 long / -1 short)."""
        legs = []
        try:
            for ln in self.VRP_LEDGER.read_text().splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if r.get("status") != "OPEN":
                    continue
                for lg in r.get("legs", []):
                    sign = -1 if "SELL" in str(lg.get("action", "")).upper() else 1
                    legs.append((lg.get("symbol"), int(r.get("quantity") or 0), sign))
        except Exception:
            pass
        try:
            for ln in self.OPT_LEDGER.read_text().splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if str(r.get("status")).upper() != "OPEN":
                    continue
                legs.append((r.get("option_symbol"), int(r.get("contracts") or 0), 1))  # long options
        except Exception:
            pass
        return [(s, q, sg) for s, q, sg in legs if s and q > 0]

    def _chain_greeks(self, underlying, expiry):
        """{option_symbol: {delta,gamma,vega,theta}} for one underlying/expiry."""
        try:
            from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
            # Tight band: we only need greeks near our held strikes (short legs ~10-12 strikes OTM,
            # wings a few more). A 200/60 pull never reaches its count and runs to the ~39s stall
            # wall; 60/30 collects the near-ATM band and breaks on COUNT in a few seconds. A leg
            # beyond the band just reads greek 0 — safe (gamma-defense checks the near-ATM shorts;
            # a missed far wing only makes net-vega read slightly MORE short, the conservative way).
            cs = TradeStationOptionChainLiveEngine().get_chain_snapshot(
                underlying, expiry, option_type="All", max_contracts=60, strike_proximity=30)
            out = {}
            for c in cs.get("contracts", []) or []:
                sym = ((c.get("Legs") or [{}])[0] or {}).get("Symbol") or c.get("Symbol")
                if sym:
                    out[str(sym).upper()] = {"delta": self._f(c.get("Delta")), "gamma": self._f(c.get("Gamma")),
                                             "vega": self._f(c.get("Vega")), "theta": self._f(c.get("Theta"))}
            return out
        except Exception:
            return {}

    def _spot(self, underlying):
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            rj = (TradeStationQuoteLiveEngine().get_quote(underlying).get("response_json") or {})
            row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
            return self._f(row.get("Last") or row.get("Close"))
        except Exception:
            return 0.0

    def book_greeks(self):
        legs = self._open_legs()
        if not legs:
            return {"timestamp": datetime.utcnow().isoformat(), "open_legs": 0,
                    "net_delta_shares": 0.0, "net_vega": 0.0, "net_gamma": 0.0, "net_theta": 0.0,
                    "per_underlying": {}, "delta_neutral": True,
                    "status": "PORTFOLIO_GREEKS_FLAT"}

        # group legs by (underlying, expiry) so we fetch each chain once
        groups = {}
        for sym, qty, sign in legs:
            und, exp = self._parse(sym)
            if und and exp:
                groups.setdefault((und, exp), []).append((str(sym).upper(), qty, sign))

        by_und = {}
        net = {"delta_shares": 0.0, "vega": 0.0, "gamma": 0.0, "theta": 0.0}
        for (und, exp), grp in groups.items():
            gmap = self._chain_greeks(und, exp)
            u = by_und.setdefault(und, {"delta_shares": 0.0, "vega": 0.0, "gamma": 0.0, "theta": 0.0,
                                        "spot": self._spot(und)})
            for sym, qty, sign in grp:
                g = gmap.get(sym)
                if not g:
                    continue
                # greeks are per-share; x100 = per contract; xqty; xsign(+long/-short). This gives
                # the position's share-equivalent delta and dollar vega/gamma/theta directly.
                mult = qty * 100 * sign
                u["delta_shares"] += g["delta"] * mult
                u["vega"] += g["vega"] * mult
                u["gamma"] += g["gamma"] * mult
                u["theta"] += g["theta"] * mult
            for k in ("delta_shares", "vega", "gamma", "theta"):
                net[k] += u[k]

        net_delta_shares = round(net["delta_shares"], 1)
        neutral = abs(net_delta_shares) <= self.DELTA_NEUTRAL_TOLERANCE_SHARES
        # delta hedge: trade -net_delta_shares of the dominant underlying to neutralise
        hedge = None
        if not neutral:
            hedge = {"action": "SELL" if net_delta_shares > 0 else "BUY",
                     "shares": abs(int(round(net_delta_shares))),
                     "note": ("book is net LONG delta (the put-tilt) — a selloff hurts twice; "
                              "sell shares to make it a pure vol bet") if net_delta_shares > 0
                     else "book is net SHORT delta — buy shares to neutralise"}
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "open_legs": len(legs),
            "net_delta_shares": net_delta_shares,
            "net_vega": round(net["vega"], 1),          # $ P&L per +1 vol point (negative = short vol)
            "net_gamma": round(net["gamma"], 2),
            "net_theta": round(net["theta"], 1),        # $ collected per day
            "delta_neutral": neutral,
            "delta_hedge": hedge,
            "hedge_armed": self._hedge_enabled(),
            "reading": ("net_vega<0 = short vol (the premium harvest); net_theta>0 = daily income; "
                        "net_delta≈0 is the goal so P&L is PURE vol, not a directional bet"),
            "per_underlying": {u: {k: round(v, 2) for k, v in d.items()} for u, d in by_und.items()},
            "status": "PORTFOLIO_GREEKS_STATUS",
        }

    def hedge_delta(self, dry_run=True):
        """Trade the underlying to bring the book delta-neutral. GATED: places a real equity order
        only when armed AND dry_run=False."""
        bg = self.book_greeks()
        h = bg.get("delta_hedge")
        if not h:
            return {"status": "ALREADY_DELTA_NEUTRAL", **bg}
        if dry_run or not self._hedge_enabled():
            return {"status": "HEDGE_DRY_RUN", "would": h,
                    "detail": "set GREYLINE_GREEKS_DELTA_HEDGE=true and dry_run=false to place the hedge"}
        # hedge the dominant underlying (largest |delta| contribution)
        und = max(bg["per_underlying"].items(), key=lambda kv: abs(kv[1].get("delta_shares", 0)))[0]
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        r = TradeStationSimBookingEngine().place_order(und, h["shares"], action=h["action"],
                                                       order_type="Market", tif="DAY")
        return {"status": "HEDGE_PLACED", "underlying": und, **h,
                "ok": r.get("ok"), "order_id": r.get("order_id")}
