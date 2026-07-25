"""Harvest the conditional VRP as a DEFINED-RISK short-premium paper strategy.

The signal is the conditional-VRP one being forward-tracked: sell premium on rich-IV (causal
trailing rank), non-earnings, liquid names. The EXPRESSION is deliberately a defined-risk IRON
CONDOR, never a naked short strangle, for one reason that overrides everything else here:

    the VRP is a RISK premium — its whole character is a fat LEFT TAIL. Selling naked vol earns a
    little most months and occasionally loses a multiple of the account in a single vol spike.
    The research showed exactly that (worst months -1000 to -4000 bps). So every position BUYS
    PROTECTIVE WINGS: the maximum loss is known and capped BEFORE the trade, and positions are
    sized so that capped loss is a small, fixed fraction of the book. The tail is bounded by
    construction, not by hope.

STRUCTURE per name (4 legs, all same ~30-45 DTE expiry):
    SELLTOOPEN  ~SHORT_DELTA call   +  BUYTOOPEN  ~WING_DELTA call   (call spread)
    SELLTOOPEN  ~SHORT_DELTA put    +  BUYTOOPEN  ~WING_DELTA put    (put spread)
  net credit = shorts' bids - wings' asks ; max loss = widest wing width x100 - credit x100.
  Contracts sized so (max loss x contracts) <= MAX_LOSS_PER_POSITION_USD.

SAFETY: this places a NEW kind of real order (short-open, four legs) with tail risk. It is
therefore DEFAULT OFF (GREYLINE_VRP_SHORT_PREMIUM_ENABLED). plan()/preview run without it and
place nothing. A name whose chain cannot supply the OTM wing strikes is SKIPPED with a reason —
we never sell the strangle without its wings just because the wings were unavailable.

EXITS (manage_positions): take profit at PROFIT_TAKE_FRAC of the credit; liquidate at
MANAGE_DTE to avoid gamma into expiry; hard-stop if the loss approaches the defined max. Always
closes as BUYTOCLOSE (shorts) + SELLTOCLOSE (wings).
"""

import json
import re
from datetime import datetime
from os import getenv
from pathlib import Path


class ConditionalVRPShortPremiumEngine:

    LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")

    SHORT_DELTA = 0.20             # sell ~20-delta strangle (≈1 SD, standard premium-selling)
    MAX_LOSS_PER_POSITION_USD = 300.0     # 3% of the $10k book, capped BEFORE the trade
    # Positions are CORRELATED — a vol spike hits every condor at once — so the tail is bounded at
    # the PORTFOLIO level, not just per position. Total defined risk across all open + new condors
    # may not exceed this. Even a simultaneous max-loss across the book stays survivable.
    PORTFOLIO_RISK_CAP_USD = 1200.0       # 12% of the book, worst-case correlated loss
    MAX_CONCURRENT = 5
    MIN_CREDIT = 0.10             # skip structures that barely pay
    PROFIT_TAKE_FRAC = 0.50       # close at 50% of max credit captured
    MANAGE_DTE = 7               # liquidate this many days before expiry (gamma risk)
    HARD_STOP_LOSS_MULT = 0.80    # stop if unrealized loss reaches 80% of defined max loss

    _SYM = re.compile(r"^(\S+)\s+(\d{6})([CP])(\d+(?:\.\d+)?)$")

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _strike(cls, option_symbol):
        m = cls._SYM.match(str(option_symbol or "").upper().strip())
        return float(m.group(4)) if m else None

    # ---------------------------------------------------------- construction

    def _leg(self, contract):
        leg = (contract.get("Legs") or [{}])[0]
        sym = leg.get("Symbol") or contract.get("Symbol")
        return {
            "symbol": sym, "strike": self._strike(sym),
            "bid": self._f(contract.get("Bid")), "ask": self._f(contract.get("Ask")),
            "delta": abs(self._f(contract.get("Delta"))),
            "oi": int(self._f(contract.get("DailyOpenInterest"))),
        }

    def build_condor(self, symbol, contracts):
        """Construct a defined-risk iron condor from a chain snapshot, or a skip reason.

        `contracts` is the raw chain list (each with Side/Bid/Ask/Delta/Legs). Returns a dict
        describing the 4 legs, net credit, max loss and sized quantity — or {'skip': reason}."""
        calls = [self._leg(c) for c in contracts
                 if c.get("Side") == "Call" and c.get("Delta") and c.get("Bid")]
        puts = [self._leg(c) for c in contracts
                if c.get("Side") == "Put" and c.get("Delta") and c.get("Bid")]
        calls = [l for l in calls if l["strike"] and l["bid"] > 0]
        puts = [l for l in puts if l["strike"] and l["bid"] > 0]
        if len(calls) < 2 or len(puts) < 2:
            return {"skip": "chain lacks call/put strikes"}

        def nearest(legs, target):
            return min(legs, key=lambda l: abs(l["delta"] - target))

        short_call = nearest(calls, self.SHORT_DELTA)
        short_put = nearest(puts, self.SHORT_DELTA)

        # ADAPTIVE WINGS: buy the WIDEST wing (most tail protection / best credit) whose resulting
        # single-condor max loss still fits the per-position cap. A wide chain gives more choices;
        # a chain that cannot cap even the nearest wing yields no trade (never a naked strangle).
        def pick_wing(cands, is_call, short_leg, other_short, other_cands):
            best = None
            for w in sorted(cands, key=lambda l: l["strike"], reverse=not is_call):
                width = (w["strike"] - short_leg["strike"]) if is_call else (short_leg["strike"] - w["strike"])
                if width <= 0:
                    continue
                # pair with the nearest affordable wing on the other side to estimate max loss
                other_w = min(other_cands, key=lambda l: abs(l["delta"] - w["delta"]), default=None)
                if not other_w:
                    continue
                credit = (short_leg["bid"] + other_short["bid"]) - (w["ask"] + other_w["ask"])
                other_width = abs(other_short["strike"] - other_w["strike"])
                max_loss = max(width, other_width) * 100 - credit * 100
                if credit >= self.MIN_CREDIT and 0 < max_loss <= self.MAX_LOSS_PER_POSITION_USD:
                    best = w                                    # widest fitting wing on this side
                    break
            return best

        call_cands = [l for l in calls if l["strike"] > short_call["strike"]]
        put_cands = [l for l in puts if l["strike"] < short_put["strike"]]
        wing_call = pick_wing(call_cands, True, short_call, short_put, put_cands)
        wing_put = pick_wing(put_cands, False, short_put, short_call, call_cands)
        if not wing_call or not wing_put:
            return {"skip": "no wing keeps one condor's max loss within the per-position cap "
                            f"(${self.MAX_LOSS_PER_POSITION_USD}) — not tradeable as defined-risk"}

        call_width = wing_call["strike"] - short_call["strike"]
        put_width = short_put["strike"] - wing_put["strike"]
        credit = (short_call["bid"] + short_put["bid"]) - (wing_call["ask"] + wing_put["ask"])
        if credit < self.MIN_CREDIT:
            return {"skip": f"credit {round(credit, 2)} below floor"}
        max_width = max(call_width, put_width)
        max_loss_per = max_width * 100 - credit * 100
        if max_loss_per <= 0 or max_loss_per > self.MAX_LOSS_PER_POSITION_USD:
            return {"skip": f"max loss ${round(max_loss_per, 0)} exceeds per-position cap"}
        qty = int(self.MAX_LOSS_PER_POSITION_USD // max_loss_per)
        if qty < 1:
            return {"skip": "cannot size within per-position cap"}

        return {
            "symbol": symbol, "quantity": qty,
            "legs": {
                "short_call": {**short_call, "action": "SELLTOOPEN"},
                "wing_call": {**wing_call, "action": "BUYTOOPEN"},
                "short_put": {**short_put, "action": "SELLTOOPEN"},
                "wing_put": {**wing_put, "action": "BUYTOOPEN"},
            },
            "credit_per_condor": round(credit, 2),
            "credit_total": round(credit * 100 * qty, 2),
            "max_loss_per_condor": round(max_loss_per, 2),
            "max_loss_total": round(max_loss_per * qty, 2),
            "call_width": call_width, "put_width": put_width,
            "return_on_risk": round(credit * 100 / max_loss_per, 3),
        }

    # ------------------------------------------------------------ planning

    def _chain(self, symbol):
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        from app.services.options_cycle_engine import OptionsCycleEngine
        exp = OptionsCycleEngine()._select_expiration(symbol)
        # strike_proximity reaches the OTM strikes the wings need (without it the stream centres on
        # near-ATM and the condor can never be capped).
        snap = TradeStationOptionChainLiveEngine().get_chain_snapshot(
            symbol=symbol, expiration=exp, option_type="All", max_contracts=160, strike_proximity=40)
        return exp, snap.get("contracts", []) or []

    def _open_rows(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines()
                    if l.strip() and json.loads(l).get("status") == "OPEN"]
        except Exception:
            return []

    def _open_symbols(self):
        return {r.get("symbol") for r in self._open_rows()}

    def _open_risk(self):
        return sum(self._f(r.get("max_loss_total")) for r in self._open_rows())

    def plan(self, names=None, limit=None):
        """Build defined-risk condors for today's rich-IV candidates. Places nothing."""
        from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine
        cands = ConditionalVRPForwardPanelEngine().rich_iv_candidates(names)
        open_syms = self._open_symbols()
        slots = max(0, self.MAX_CONCURRENT - len(open_syms))
        open_risk = self._open_risk()
        budget_left = self.PORTFOLIO_RISK_CAP_USD - open_risk
        built, skipped = [], []
        for c in cands:
            if len(built) >= (limit if limit is not None else slots):
                break
            if c["ticker"] in open_syms:
                continue
            try:
                exp, contracts = self._chain(c["ticker"])
            except Exception as e:
                skipped.append({"ticker": c["ticker"], "skip": f"chain error: {str(e)[:60]}"})
                continue
            con = self.build_condor(c["ticker"], contracts)
            if con.get("skip"):
                skipped.append({"ticker": c["ticker"], "skip": con["skip"]})
                continue
            # PORTFOLIO tail cap: condors are correlated (a vol spike hits them together), so total
            # defined risk across the book is bounded, not just each position.
            if con["max_loss_total"] > budget_left:
                skipped.append({"ticker": c["ticker"],
                                "skip": f"would exceed portfolio risk cap (${round(budget_left, 0)} left)"})
                continue
            budget_left -= con["max_loss_total"]
            con.update({"expiration": exp, "iv_rank": c["iv_rank"], "iv": c["iv"]})
            built.append(con)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "enabled": self.enabled(),
            "candidates": len(cands), "open_positions": len(open_syms),
            "free_slots": slots, "planned": built, "skipped": skipped[:20],
            "cap_per_position_usd": self.MAX_LOSS_PER_POSITION_USD,
            "total_defined_risk_usd": round(sum(b["max_loss_total"] for b in built), 2),
            "status": "VRP_SHORT_PREMIUM_PLAN",
        }

    # ------------------------------------------------------------ booking (GATED)

    def _booking(self):
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        return TradeStationSimBookingEngine()

    @staticmethod
    def _tick_round(price, is_option=True):
        return round(round(price / 0.05) * 0.05, 2) if is_option else round(price, 2)

    def open_positions(self, names=None, dry_run=True, limit=None):
        """Place the planned defined-risk condors. GATED: does nothing unless enabled AND
        dry_run is False. Books 4 legs per condor (shorts SELLTOOPEN, wings BUYTOOPEN) and records
        the condor as one OPEN ledger unit."""
        pl = self.plan(names=names, limit=limit)
        if dry_run or not self.enabled():
            pl["note"] = ("DRY RUN — nothing placed. Set GREYLINE_VRP_SHORT_PREMIUM_ENABLED=true "
                          "and call with dry_run=false to book. Every position is defined-risk.")
            return pl

        b = self._booking()
        opened, errors = [], []
        for con in pl["planned"]:
            qty = con["quantity"]
            placed_legs, leg_err = [], False
            # BUY the wings FIRST so the tail cap exists before the short legs are live.
            order = [("wing_call", "BUYTOOPEN"), ("wing_put", "BUYTOOPEN"),
                     ("short_call", "SELLTOOPEN"), ("short_put", "SELLTOOPEN")]
            for name, action in order:
                leg = con["legs"][name]
                px = leg["ask"] if action == "BUYTOOPEN" else leg["bid"]   # marketable limit
                r = b.place_order(leg["symbol"], qty, action=action, order_type="Limit",
                                  limit_price=self._tick_round(px), tif="DAY")
                if r.get("ok"):
                    placed_legs.append({"symbol": leg["symbol"], "action": action,
                                        "order_id": r.get("order_id"), "limit": self._tick_round(px)})
                else:
                    leg_err = True
                    errors.append({"symbol": leg["symbol"], "http": r.get("http_status")})
                    break
            if leg_err:
                continue
            rec = {
                "symbol": con["symbol"], "quantity": qty, "expiration": con["expiration"],
                "legs": placed_legs, "credit_per_condor": con["credit_per_condor"],
                "credit_total": con["credit_total"], "max_loss_total": con["max_loss_total"],
                "opened_at": datetime.utcnow().isoformat(), "status": "OPEN",
            }
            self.LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(rec) + "\n")
            opened.append({"symbol": con["symbol"], "qty": qty,
                           "credit": con["credit_total"], "max_loss": con["max_loss_total"]})
        return {"timestamp": datetime.utcnow().isoformat(), "opened": opened,
                "errors": errors, "status": "VRP_SHORT_PREMIUM_OPENED"}

    # ------------------------------------------------------------ exit doctrine

    def _dte(self, expiration):
        try:
            e = datetime.strptime(str(expiration)[:10], "%Y-%m-%d").date()
            return (e - datetime.utcnow().date()).days
        except Exception:
            return 999

    def manage_positions(self, dry_run=True):
        """Exit doctrine for open condors: take profit at PROFIT_TAKE_FRAC of credit, liquidate at
        MANAGE_DTE, or hard-stop near the defined max loss. Close = BUYTOCLOSE shorts + SELLTOCLOSE
        wings. Returns the decisions (acts only when enabled and not dry_run)."""
        try:
            rows = [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return {"status": "NO_VRP_LEDGER", "managed": 0}
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        q = TradeStationQuoteLiveEngine()

        decisions = []
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            # current cost to CLOSE the condor = pay to buy back shorts, receive to sell wings
            cost_to_close = 0.0
            priced = True
            for leg in r["legs"]:
                qd = (q.get_quote(leg["symbol"]).get("response_json") or {})
                row = (qd.get("Quotes") or [qd])[0] if isinstance(qd, dict) else {}
                bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
                if bid <= 0 or ask <= 0:
                    priced = False
                    break
                mid = (bid + ask) / 2
                cost_to_close += mid if leg["action"] == "SELLTOOPEN" else -mid  # buy back shorts, sell wings
            if not priced:
                decisions.append({"symbol": r["symbol"], "action": "HOLD", "reason": "stale quote"})
                continue
            credit = r["credit_per_condor"]
            pnl_per = (credit - cost_to_close) * 100          # + = profit
            pnl_total = pnl_per * r["quantity"]
            dte = self._dte(r.get("expiration"))
            max_loss_total = r["max_loss_total"]

            reason = None
            if pnl_per >= self.PROFIT_TAKE_FRAC * credit * 100:
                reason = "PROFIT_TAKE_50PCT"
            elif dte <= self.MANAGE_DTE:
                reason = f"MANAGE_DTE_{dte}D"
            elif pnl_total <= -self.HARD_STOP_LOSS_MULT * max_loss_total:
                reason = "HARD_STOP_NEAR_MAX_LOSS"
            if not reason:
                decisions.append({"symbol": r["symbol"], "action": "HOLD",
                                  "pnl": round(pnl_total, 2), "dte": dte})
                continue

            if self.enabled() and not dry_run:
                b = self._booking()
                for leg in r["legs"]:
                    close_action = "BUYTOCLOSE" if leg["action"] == "SELLTOOPEN" else "SELLTOCLOSE"
                    b.place_order(leg["symbol"], r["quantity"], action=close_action,
                                  order_type="Market", tif="DAY")
                r["status"] = "CLOSED"; r["closed_at"] = datetime.utcnow().isoformat()
                r["close_reason"] = reason; r["realized_pnl"] = round(pnl_total, 2)
            decisions.append({"symbol": r["symbol"], "action": "CLOSE", "reason": reason,
                              "pnl": round(pnl_total, 2), "dte": dte})

        if self.enabled() and not dry_run and any(d["action"] == "CLOSE" for d in decisions):
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        return {"timestamp": datetime.utcnow().isoformat(),
                "managed": len(decisions), "decisions": decisions,
                "acted": bool(self.enabled() and not dry_run), "status": "VRP_SHORT_PREMIUM_MANAGED"}

