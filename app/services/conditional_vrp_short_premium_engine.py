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

STRUCTURE per name (4 legs, all same expiry; tenor chosen by AdaptiveDTESelectionEngine — the
EV-best expiration in a 28-56 DTE band from the live market, not a fixed literal):
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


# The DISTINCT-underlying high-VRP index harvest set (measured 2026-07-26, VRP >= ~10% of IV).
# Redundant S&P clones (VOO/IVV/VTI) collapsed to SPY — selling all of them is 4x the same crash
# bet, not diversification. Kept: distinct underlyings across size/style/sector/region, so the
# IDIOSYNCRATIC vol diversifies (better non-crash Sharpe) while the portfolio cap bounds the one
# risk that does NOT diversify — a correlated market crash.
INDEX_ETFS = ["SPY", "RSP", "MDY", "IWM", "DIA", "QQQ",
              "XLF", "XLE", "XLY", "XLC", "XLU", "XLB", "XLRE",
              "VWO", "FXI"]

# CROSS-ASSET variance premium (measured 2026-07-26): non-equity vol that is ALSO overpriced but
# whose tail is a DIFFERENT crash — a bond selloff / credit event / oil spike / dollar move, not a
# stock crash. Correlations of monthly VRP with SPY's: rates 0.23-0.27, credit -0.07/0.26, oil 0.00,
# dollar -0.22 (a partial equity-crash hedge). This is what breaks the single-crash concentration
# of index vol selling — independent tails instead of one. Gold/silver EXCLUDED (negative VRP: their
# vol is underpriced). The cost gate skips any that are too illiquid to trade defined-risk.
CROSS_ASSET_ETFS = ["TLT", "IEF", "HYG", "LQD", "USO", "UUP"]

# The full diversified variance-premium harvest: equity-index crash premium PLUS independent-tail
# cross-asset premiums. The portfolio cap still bounds the worst case, but that worst case is now
# spread across uncorrelated risk drivers rather than concentrated in one equity crash.
VARIANCE_HARVEST = INDEX_ETFS + CROSS_ASSET_ETFS


class ConditionalVRPShortPremiumEngine:

    LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")

    # ASYMMETRIC PUT-TILT (measured 2026-07-26): the index variance premium is concentrated in an
    # OVERPRICED put skew — OTM put IV runs ~7-12 vol pts above OTM call IV while realized downside
    # asymmetry is only ~1.4. So sell the PUT nearer the money (richer skew = more premium) and the
    # CALL further out (call skew is cheap; less premium given up, and it trims upside risk). The
    # tilt is DELIBERATELY MODEST (25d put / 15d call, vs a symmetric 20/20): a heavier tilt would
    # concentrate crash exposure and undo the cross-asset diversification. Set both equal to go
    # symmetric. Env-overridable for tuning the premium-vs-crash-concentration dial.
    SHORT_DELTA = 0.20             # reference / symmetric fallback
    SHORT_PUT_DELTA = 0.25         # put nearer ATM — capture the overpriced put skew
    SHORT_CALL_DELTA = 0.15        # call further OTM — cheap skew, less premium there, less upside risk
    MAX_ADAPT_SHORT_DELTA = 0.40   # band-aware fallback ceiling: when the SIM's narrow strike band can't
    #                                reach the target-delta short, place the short as far OTM as the band
    #                                allows — but NEVER closer than this (a >0.40-delta short is a near-ATM
    #                                coin flip, not a premium harvest); skip instead.
    DEFAULT_MAX_LOSS_PER_POSITION_USD = 500.0   # fallback/floor if the resolver is unavailable
    # Positions are CORRELATED — a vol spike hits every condor at once — so the tail is bounded at
    # the PORTFOLIO level, not just per position. Total defined risk across all open + new condors
    # may not exceed this. Even a simultaneous max-loss across the book stays survivable.
    DEFAULT_PORTFOLIO_RISK_CAP_USD = 1200.0   # fallback if the equity read fails (was the static cap)
    # VEGA BUDGET: a vol desk sizes by its net vol EXPOSURE, not just its max loss. This caps the
    # book's total net SHORT vega (|$ P&L per +1 vol point|). At -300, a 4-vol-pt spike ~= the
    # portfolio dollar cap, so the two risk metrics agree. Env-tunable (GREYLINE_VEGA_BUDGET_USD).
    MAX_SHORT_VEGA_USD = 300.0
    MAX_CONCURRENT = 5
    SKEW_POOL = 8                 # build this many candidates, then harvest the richest-skew ones
    MIN_CREDIT = 0.10             # skip structures that barely pay
    PROFIT_TAKE_FRAC = 0.50       # close at 50% of max credit captured
    MANAGE_DTE = 21              # exit this many days before expiry — before terminal gamma (the
    #                             "manage at 21 DTE" rule). Sits BELOW the 28-DTE entry-band floor
    #                             (AdaptiveDTESelectionEngine) so entry and exit can never collide.
    HARD_STOP_LOSS_MULT = 0.80    # stop if unrealized loss reaches 80% of defined max loss
    # GAMMA DEFENSE: a short leg whose delta has grown to this means the underlying is TESTING that
    # strike — short gamma is now acute and the strike is at risk of breach. Close proactively,
    # before it becomes a max-loss hard stop. This is the "manage the tested side" discipline that
    # lets SAFE (centered) condors keep harvesting theta while cutting THREATENED ones early.
    TESTED_SHORT_DELTA = 0.45

    _SYM = re.compile(r"^(\S+)\s+(\d{6})([CP])(\d+(?:\.\d+)?)$")

    @property
    def PORTFOLIO_RISK_CAP_USD(self):
        # Now %-of-equity (scales with the account) instead of a static $1,200. It's a defined-RISK
        # cap (worst-case correlated max loss), NOT a cash outlay, so it's scaled off equity but NOT
        # clamped to cash. Resolved LAZILY on first access and cached, so merely constructing the
        # engine (e.g. for build_condor) does NO broker read. getattr(eng, "PORTFOLIO_RISK_CAP_USD")
        # — used by the premium-harvest OS and opportunity board — sees the live value. Settable
        # (tests / overrides); falls back to the class default if the resolver is unavailable.
        cached = getattr(self, "_prc_cache", None)
        if cached is not None:
            return cached
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            val = SleeveCapitalBudgetEngine.budget_usd("vrp", clamp_to_cash=False)
        except Exception:
            val = type(self).DEFAULT_PORTFOLIO_RISK_CAP_USD
        self._prc_cache = val
        return val

    @PORTFOLIO_RISK_CAP_USD.setter
    def PORTFOLIO_RISK_CAP_USD(self, value):
        self._prc_cache = float(value)

    @property
    def MAX_LOSS_PER_POSITION_USD(self):
        # Per-condor max-loss cap, now %-of-equity with a floor (max(5% equity, $500)) via the central
        # SleeveCapitalBudgetEngine — scales with the book, never below the min viable defined-risk size.
        # Lazy cached (no broker read on construct); getattr readers (build_condor, status, premium-harvest,
        # earnings via this instance) all see the live value. Settable for tests. Falls back to the default.
        cached = getattr(self, "_pcl_cache", None)
        if cached is not None:
            return cached
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            val = SleeveCapitalBudgetEngine.per_condor_max_loss()
        except Exception:
            val = type(self).DEFAULT_MAX_LOSS_PER_POSITION_USD
        self._pcl_cache = val
        return val

    @MAX_LOSS_PER_POSITION_USD.setter
    def MAX_LOSS_PER_POSITION_USD(self, value):
        self._pcl_cache = float(value)

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _atomic_orders_enabled():
        """Place condors as a single ATOMIC multi-leg order (no naked-leg window). Gated OFF by default
        until the SIM's multi-leg support is verified; the legged-in path + naked auto-remediation are
        the fallback. Flag: GREYLINE_CONDOR_ATOMIC_ORDER."""
        return (getenv("GREYLINE_CONDOR_ATOMIC_ORDER", "") or "").strip().lower() == "true"

    @classmethod
    def _vega_budget(cls):
        try:
            return abs(float(getenv("GREYLINE_VEGA_BUDGET_USD", "") or cls.MAX_SHORT_VEGA_USD))
        except (TypeError, ValueError):
            return cls.MAX_SHORT_VEGA_USD

    def _current_book_vega(self):
        """Net vega already on the book (open positions), so new harvest sizes on top of it."""
        try:
            from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
            return self._f(PortfolioGreeksEngine().book_greeks().get("net_vega"))
        except Exception:
            return 0.0

    @classmethod
    def _put_delta(cls):
        try:
            return float(getenv("GREYLINE_VRP_SHORT_PUT_DELTA", "") or cls.SHORT_PUT_DELTA)
        except (TypeError, ValueError):
            return cls.SHORT_PUT_DELTA

    @classmethod
    def _call_delta(cls):
        try:
            return float(getenv("GREYLINE_VRP_SHORT_CALL_DELTA", "") or cls.SHORT_CALL_DELTA)
        except (TypeError, ValueError):
            return cls.SHORT_CALL_DELTA

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
            "iv": self._f(contract.get("ImpliedVolatility")),
            "vega": self._f(contract.get("Vega")),
            "oi": int(self._f(contract.get("DailyOpenInterest"))),
        }

    def build_condor(self, symbol, contracts, put_delta=None, call_delta=None, max_loss_cap=None):
        """Construct a defined-risk iron condor from a chain snapshot, or a skip reason.

        `contracts` is the raw chain list (each with Side/Bid/Ask/Delta/Legs). Defaults to the
        asymmetric put-tilt (put nearer ATM); a caller can force specific short deltas. `max_loss_cap`
        overrides the per-condor max-loss ceiling (earnings uses a higher cap than VRP so higher-priced
        names with wider strike spacing still qualify as defined-risk). Returns the 4 legs, net credit,
        max loss and sized quantity — or {'skip': reason}."""
        cap = self.MAX_LOSS_PER_POSITION_USD if max_loss_cap is None else float(max_loss_cap)
        put_delta = self._put_delta() if put_delta is None else put_delta
        call_delta = self._call_delta() if call_delta is None else call_delta
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

        # BAND-AWARE short selection. The SIM sandbox lists only a narrow strike band (it ignores
        # strikeProximity), so on a high-IV name the far-OTM target-delta strike can fall OUTSIDE the
        # band — or land on the OUTERMOST strike, leaving no room for a wing beyond it (the exact reason
        # rich-IV names skipped). Restrict shorts to strikes that HAVE a further-OTM strike available
        # (so a protective wing can be bought), then take the one nearest the target delta — i.e. as far
        # OTM as the band allows. A quality floor (MAX_ADAPT_SHORT_DELTA) still refuses a near-ATM short.
        max_call_k = max((l["strike"] for l in calls), default=None)
        min_put_k = min((l["strike"] for l in puts), default=None)
        call_short_pool = [l for l in calls if max_call_k is not None and l["strike"] < max_call_k]
        put_short_pool = [l for l in puts if min_put_k is not None and l["strike"] > min_put_k]
        if not call_short_pool or not put_short_pool:
            return {"skip": "strike band too narrow to place a short with a wing beyond it"}
        short_call = nearest(call_short_pool, call_delta)
        short_put = nearest(put_short_pool, put_delta)
        if abs(short_call["delta"]) > self.MAX_ADAPT_SHORT_DELTA or abs(short_put["delta"]) > self.MAX_ADAPT_SHORT_DELTA:
            return {"skip": f"strike band too narrow — the furthest-OTM placeable short is >"
                            f"{self.MAX_ADAPT_SHORT_DELTA} delta (too close to ATM to sell)"}

        # ADAPTIVE WINGS: buy the WIDEST wing (most tail protection / best credit) whose resulting
        # single-condor max loss still fits the per-position cap. A wide chain gives more choices;
        # a chain that cannot cap even the nearest wing yields no trade (never a naked strangle).
        def pick_wing(cands, is_call, short_leg, other_short, other_cands):
            best = None
            for w in sorted(cands, key=lambda l: l["strike"], reverse=not is_call):
                width = (w["strike"] - short_leg["strike"]) if is_call else (short_leg["strike"] - w["strike"])
                if width <= 0:
                    continue
                # pair with the SAME-WIDTH wing on the other side (a symmetric condor). Matching by
                # DELTA instead mated a near wing on one side with a FAR wing on the other, inflating
                # max loss (via max(width, other_width)) and wrongly blocking otherwise-valid condors.
                other_target = (other_short["strike"] - width) if is_call else (other_short["strike"] + width)
                other_w = min(other_cands, key=lambda l: abs(l["strike"] - other_target), default=None)
                if not other_w:
                    continue
                credit = (short_leg["bid"] + other_short["bid"]) - (w["ask"] + other_w["ask"])
                other_width = abs(other_short["strike"] - other_w["strike"])
                max_loss = max(width, other_width) * 100 - credit * 100
                if credit >= self.MIN_CREDIT and 0 < max_loss <= cap:
                    best = w                                    # widest fitting wing on this side
                    break
            return best

        call_cands = [l for l in calls if l["strike"] > short_call["strike"]]
        put_cands = [l for l in puts if l["strike"] < short_put["strike"]]
        wing_call = pick_wing(call_cands, True, short_call, short_put, put_cands)
        wing_put = pick_wing(put_cands, False, short_put, short_call, call_cands)
        if not wing_call or not wing_put:
            return {"skip": "no wing keeps one condor's max loss within the per-position cap "
                            f"(${cap}) — not tradeable as defined-risk"}

        call_width = wing_call["strike"] - short_call["strike"]
        put_width = short_put["strike"] - wing_put["strike"]
        credit = (short_call["bid"] + short_put["bid"]) - (wing_call["ask"] + wing_put["ask"])
        if credit < self.MIN_CREDIT:
            return {"skip": f"credit {round(credit, 2)} below floor"}
        max_width = max(call_width, put_width)
        max_loss_per = max_width * 100 - credit * 100
        if max_loss_per <= 0 or max_loss_per > cap:
            return {"skip": f"max loss ${round(max_loss_per, 0)} exceeds per-position cap"}
        qty = int(cap // max_loss_per)
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
            "short_put_delta": round(short_put["delta"], 3),
            "short_call_delta": round(short_call["delta"], 3),
            "put_tilt": round(short_put["delta"] - short_call["delta"], 3),  # >0 = put nearer ATM
            # skew of the sold legs (put IV - call IV). Steeper = richer premium (skew-timing study
            # 2026-07-26: steep skew -> ~54% more put-VRP). Used to PRIORITISE which names to harvest,
            # NOT to size up — the study's tail-safety at steep skew is a crash-free-sample mirage.
            "skew": round(short_put["iv"] - short_call["iv"], 4)
            if (short_put.get("iv") and short_call.get("iv")) else None,
            # net vega of the condor ($ P&L per +1 vol pt): wings (long) minus shorts (short). Net
            # NEGATIVE = short vol. This is the vol-exposure the vega budget is sized against.
            "net_vega": round(((wing_put["vega"] + wing_call["vega"])
                               - (short_put["vega"] + short_call["vega"])) * 100 * qty, 1),
        }

    # ------------------------------------------------------------ planning

    def _chain(self, symbol):
        # PRIMARY: Unusual Whales. The TradeStation SIM sandbox streams only a narrow, garbage-quoted
        # strike band (a $1-fair wing quoted at $4), so a defined-risk condor could never form on it.
        # UW gives clean per-strike greeks + NBBO; prefer a liquid MONTHLY expiry near the DTE target
        # (the adaptive engine sometimes picks a weekly with ~0 two-sided quotes even on SPY).
        from app.services.uw_option_chain_engine import UWOptionChainEngine
        uw = UWOptionChainEngine()
        if uw.enabled():
            try:
                target = int(getenv("GREYLINE_DTE_TARGET", "") or 42)
                exp = uw.monthly_expiry(target_dte=target)
                if exp:
                    snap = uw.get_chain_snapshot(symbol=symbol, expiration=exp)
                    if snap.get("contracts"):
                        return exp, snap["contracts"]
            except Exception:
                pass
        # FALLBACK: TradeStation sandbox chain (adaptive EV-best expiry within the sane band).
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        from app.services.adaptive_dte_selection_engine import AdaptiveDTESelectionEngine
        exp = AdaptiveDTESelectionEngine().select(symbol)
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

    def condor_display_levels(self):
        """{leg_symbol: unit management levels} for the dashboard. A condor's stop/profit-take are
        on the WHOLE unit's P&L (not per leg), so the same levels are surfaced against each of its
        legs — that's what actually protects the position."""
        out = {}
        for r in self._open_rows():
            credit = self._f(r.get("credit_total"))
            max_loss = self._f(r.get("max_loss_total"))
            if max_loss <= 0:
                continue
            info = {
                "condor": r.get("symbol"),
                "profit_take_usd": round(credit * self.PROFIT_TAKE_FRAC, 2),   # +50% of credit
                "hard_stop_usd": round(-self.HARD_STOP_LOSS_MULT * max_loss, 2),  # -80% of max loss
                "max_loss_usd": round(max_loss, 2),
                "credit_usd": round(credit, 2),
                "manage_dte": self.MANAGE_DTE,
                "dte": self._dte(r.get("expiration")),
            }
            for lg in r.get("legs", []) or []:
                s = str(lg.get("symbol") or "").upper()
                if s:
                    out[s] = info
        return out

    _LEG_RE = re.compile(r"^[A-Z.]+\s+\d{6}([CP])(\d+(?:\.\d+)?)$")

    def _broker_fills(self):
        """{option_symbol: {'avg': fill_price, 'long': bool}} from the LIVE broker — the source of
        truth for what actually filled and at what price."""
        out = {}
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            for x in ((TradeStationPositionsLiveEngine().get_positions().get("response_json") or {})
                      .get("Positions") or []):
                if x.get("AssetType") == "STOCKOPTION":
                    out[str(x.get("Symbol") or "").upper()] = {
                        "avg": self._f(x.get("AveragePrice")),
                        "long": str(x.get("LongShort") or "").lower() == "long"}
        except Exception:
            pass
        return out

    def reconcile_fills(self, dry_run=False):
        """Rewrite each OPEN condor's credit/max-loss from the ACTUAL broker fills, counting only the
        legs that actually filled. Fixes: (1) recorded credit was the PLANNED limit price, not the
        fill; (2) unfilled legs were counted as if real. Flags a naked short (a filled short with no
        filled protective wing) — undefined risk that must never be silently carried."""
        try:
            rows = [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return {"status": "NO_VRP_LEDGER", "reconciled": 0}
        fills = self._broker_fills()
        changed, nakeds = [], []
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            qty = int(r.get("quantity") or 0)
            parsed = []
            for lg in r.get("legs", []) or []:
                sym = str(lg.get("symbol") or "").upper()
                m = self._LEG_RE.match(sym)
                if not m:
                    continue
                f = fills.get(sym)
                parsed.append({"type": m.group(1), "strike": float(m.group(2)),
                               "short": "SELL" in str(lg.get("action", "")).upper(),
                               "fill": (f["avg"] if f else None), "lg": lg})
            filled = [p for p in parsed if p["fill"] is not None]
            if not filled:
                continue
            # net credit PER SHARE from the filled legs (short = received +, long = paid -)
            net = sum((p["fill"] if p["short"] else -p["fill"]) for p in filled)

            def width(typ):
                shorts = [p for p in filled if p["type"] == typ and p["short"]]
                wings = [p for p in filled if p["type"] == typ and not p["short"]]
                if shorts and not wings:
                    return None                                   # filled short, no filled wing = NAKED
                if shorts and wings:
                    return abs(wings[0]["strike"] - shorts[0]["strike"])
                return 0.0
            cw, pw = width("C"), width("P")
            naked = cw is None or pw is None
            for p in parsed:                                       # record real fills for transparency
                if p["fill"] is not None:
                    p["lg"]["fill_price"] = p["fill"]
            credit_total = round(net * 100 * qty, 2)
            old_c, old_ml = self._f(r.get("credit_total")), self._f(r.get("max_loss_total"))
            if naked:
                r["naked_exposure"] = True
                # SAFETY NET: don't just alert — auto-complete the missing tail cap. Only when the sleeve
                # AND booking are genuinely live (never auto-trade a disabled book), and bounded by a retry
                # cap so a persistently-unfillable wing can't loop. See _remediate_naked.
                remediation = None
                if not dry_run and self.enabled() and self._booking_active():
                    try:
                        remediation = self._remediate_naked(r, parsed, self._booking())
                    except Exception as e:
                        remediation = [{"error": repr(e)[:120]}]
                nakeds.append({"symbol": r.get("symbol"), "note": "filled short with no filled wing",
                               "attempts": r.get("naked_remediation_attempts"), "remediation": remediation})
                continue                                           # do NOT overwrite risk with a wrong cap
            r.pop("naked_exposure", None)
            max_w = max([w for w in (cw, pw)] or [0.0])
            max_loss_total = round(max_w * 100 * qty - credit_total, 2)
            if (abs(credit_total - old_c) >= 0.01 or abs(max_loss_total - old_ml) >= 0.01
                    or not r.get("fill_reconciled")):
                # OPEN-side execution slippage → ExecutionLog, ONCE, BEFORE we overwrite the plan credit:
                # the plan (decision-mid) credit vs the ACTUAL fill credit. Selling the condor to collect
                # premium → action SELL; collecting LESS than the mid is a cost. ONLY when EVERY leg filled
                # (len(filled)==len(parsed)) — else `net` is a partial-spread credit while decision_credit is
                # the full condor, which would log a large bogus slippage that's really the missing spread.
                if not dry_run and not r.get("open_slippage_logged") and len(filled) == len(parsed):
                    decision_credit = self._f(r.get("credit_per_condor"))   # still the plan here
                    try:
                        from app.services.execution_log_engine import ExecutionLogEngine
                        _sleeve = "premium_earnings" if str(r.get("strategy")) == "earnings_vol" else "premium_vrp"
                        ExecutionLogEngine().record_fill(_sleeve, r.get("symbol"), "SELL",
                                                         int(qty) * 100, mid=decision_credit, fill=net)
                        r["open_slippage_logged"] = True
                    except Exception:
                        pass
                changed.append({"symbol": r.get("symbol"),
                                "credit_total": {"was": old_c, "now": credit_total},
                                "max_loss_total": {"was": old_ml, "now": max_loss_total},
                                "filled_legs": len(filled), "total_legs": len(parsed)})
                r["credit_total"] = credit_total
                r["credit_per_condor"] = round(net, 4)
                r["max_loss_total"] = max_loss_total
                r["filled_leg_count"] = len(filled)
                r["fill_reconciled"] = True
        if not dry_run and (changed or nakeds):
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        if nakeds:
            try:
                from app.services.external_alert_engine import ExternalAlertEngine
                eng = ExternalAlertEngine()
                if eng.has_external_channel():
                    acted = any(n.get("remediation") for n in nakeds)
                    tail = (" Auto-remediation is completing the missing wing — verify it filled next cycle."
                            if acted else
                            " Auto-remediation is OFF (sleeve/booking disabled) — complete the wing or "
                            "buy-to-close the short MANUALLY.")
                    syms = sorted(str(n.get("symbol")) for n in nakeds)
                    eng.dispatch(
                        title="GreyLine NAKED option exposure" + (" — auto-remediating" if acted else ""),
                        message=f"reconciler found a filled short with no filled wing: {syms}." + tail,
                        severity="CRITICAL",
                        # fingerprint on the STABLE symbol set (not the per-cycle remediation detail) so the
                        # cooldown dedup actually works and doesn't re-page every cycle.
                        fingerprint=f"VRP_NAKED:{syms}")
            except Exception:
                pass
        return {"timestamp": datetime.utcnow().isoformat(), "reconciled": len(changed),
                "changes": changed, "naked": nakeds,
                "status": "VRP_FILLS_RECONCILED" if not dry_run else "VRP_FILLS_RECONCILE_DRYRUN"}

    # ---- naked-exposure auto-remediation (the safety net) --------------------------------------
    MAX_NAKED_REMEDIATION_ATTEMPTS = 3

    @staticmethod
    def _booking_active():
        """Only auto-trade a remediation when execution is genuinely live — never touch a disabled book."""
        return ((getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "") or "").strip().lower() == "true"
                and (getenv("GREYLINE_SIM_BOOKING_ENABLED", "") or "").strip().lower() == "true")

    @staticmethod
    def _option_ask(q, sym):
        try:
            rj = (q.get_quote(sym).get("response_json") or {})
            row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
            a = float(row.get("Ask") or 0)
            return a if a > 0 else None
        except Exception:
            return None

    def _remediate_naked(self, r, parsed, b):
        """Auto-complete a naked condor: cancel each unfilled wing's stale (unfillable) limit order and
        re-buy the wing at a marketable limit, restoring the tail cap — exactly the manual procedure.
        Bounded by MAX_NAKED_REMEDIATION_ATTEMPTS; once those are spent and it's still naked, buy-to-close
        the still-uncovered short(s) — a guaranteed way to remove the undefined risk. Records actions on
        the ledger row for transparency."""
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        q = TradeStationQuoteLiveEngine()
        qty = int(r.get("quantity") or 0)
        attempts = int(r.get("naked_remediation_attempts") or 0)
        actions = []
        if qty <= 0:
            return actions
        unfilled_wings = [p for p in parsed if not p["short"] and p["fill"] is None]

        def wing_missing(short_p):
            return not any((not w["short"]) and w["type"] == short_p["type"] and w["fill"] is not None
                           for w in parsed)
        uncovered_shorts = [p for p in parsed if p["short"] and p["fill"] is not None and wing_missing(p)]

        if attempts < self.MAX_NAKED_REMEDIATION_ATTEMPTS and unfilled_wings:
            for p in unfilled_wings:
                sym = p["lg"]["symbol"]
                oid = p["lg"].get("order_id")
                if oid:
                    try:
                        b.cancel_order(oid)                        # kill the stale limit before re-buying
                    except Exception:
                        pass
                ask = self._option_ask(q, sym)
                if not ask:
                    actions.append({"wing": sym, "action": "rebuy", "ok": False, "reason": "no ask quote"})
                    continue
                px = self._tick_round(ask)
                rr = b.place_order(sym, qty, action="BUYTOOPEN", order_type="Limit",
                                   limit_price=px, tif="DAY")
                if rr.get("ok") and rr.get("order_id"):
                    p["lg"]["order_id"] = rr.get("order_id")     # track the new order for next-cycle checks
                actions.append({"wing": sym, "action": "rebuy_marketable", "ok": rr.get("ok"),
                                "order_id": rr.get("order_id"), "limit": px,
                                "reject": rr.get("reject_reason")})
            r["naked_remediation_attempts"] = attempts + 1
        elif uncovered_shorts:
            # retries exhausted and still naked → cover the short outright (defined risk beats a live naked)
            for p in uncovered_shorts:
                sym = p["lg"]["symbol"]
                ask = self._option_ask(q, sym)
                if not ask:
                    actions.append({"short": sym, "action": "cover", "ok": False, "reason": "no ask quote"})
                    continue
                rr = b.place_order(sym, qty, action="BUYTOCLOSE", order_type="Limit",
                                   limit_price=self._tick_round(ask), tif="DAY")
                actions.append({"short": sym, "action": "cover_last_resort", "ok": rr.get("ok"),
                                "order_id": rr.get("order_id"), "reject": rr.get("reject_reason")})
        return actions

    def plan(self, names=None, limit=None):
        """Build defined-risk condors for today's rich-IV candidates. Places nothing."""
        from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine
        cands = ConditionalVRPForwardPanelEngine().rich_iv_candidates(names)
        open_syms = self._open_symbols()
        slots = max(0, self.MAX_CONCURRENT - len(open_syms))
        open_risk = self._open_risk()
        budget_left = self.PORTFOLIO_RISK_CAP_USD - open_risk
        want = limit if limit is not None else slots

        # SKEW-CONDITIONED SELECTION: build condors for a bounded candidate POOL, then take the
        # RICHEST-SKEW ones (skew-timing study: steep skew ~= 54% more premium). This harvests the
        # most-overpriced opportunities at the SAME defined-risk size — more premium per unit of the
        # same bounded tail. Deliberately NOT sizing up on skew: the study's tail-safety at steep
        # skew is a crash-free-sample mirage, so skew picks WHAT to sell, never how much risk to bear.
        candidates, skipped = [], []
        for c in cands:
            if len(candidates) >= self.SKEW_POOL:
                break
            if c["ticker"] in open_syms:
                continue
            try:
                exp, contracts = self._chain(c["ticker"])
            except Exception as e:
                skipped.append({"ticker": c["ticker"], "skip": f"chain error: {str(e)[:60]}"})
                continue
            con = self.build_condor(c["ticker"], contracts)
            if con.get("skip") and "cap" in con["skip"]:
                sym = self.build_condor(c["ticker"], contracts,
                                        put_delta=self.SHORT_DELTA, call_delta=self.SHORT_DELTA)
                if not sym.get("skip"):
                    sym["tilt_fallback"] = "symmetric (put-tilt exceeded the cap)"
                    con = sym
            if con.get("skip"):
                skipped.append({"ticker": c["ticker"], "skip": con["skip"]})
                continue
            con.update({"expiration": exp, "iv_rank": c["iv_rank"], "iv": c["iv"]})
            candidates.append(con)

        # RETURN-ON-RISK first (premium captured per dollar of defined risk), skew as the tiebreaker.
        # The portfolio risk cap is finite, so whoever fills it first wins — that has to be the highest
        # premium-per-risk condor, NOT merely the steepest-skew one. Skew still says which tail is most
        # overpriced, but on its own it let a 4.6%-ROR name crowd out a 25%-ROR name once the budget was
        # spent. Rank by ROR, break ties by skew, then fill within slots, the DOLLAR cap AND the VEGA
        # BUDGET — the two risk dimensions a vol desk manages: max loss (tail) and vol exposure.
        candidates.sort(
            key=lambda x: (
                x.get("return_on_risk") if x.get("return_on_risk") is not None else -9,
                x.get("skew") if x.get("skew") is not None else -9,
            ),
            reverse=True,
        )
        vega_budget = self._vega_budget()
        vega_used = abs(self._current_book_vega())     # net short vega already on the book
        built = []
        for con in candidates:
            if len(built) >= want:
                break
            if con["max_loss_total"] > budget_left:
                skipped.append({"ticker": con["symbol"],
                                "skip": f"would exceed portfolio risk cap (${round(budget_left, 0)} left)"})
                continue
            con_vega = abs(self._f(con.get("net_vega")))
            if con_vega and vega_used + con_vega > vega_budget:
                skipped.append({"ticker": con["symbol"],
                                "skip": f"would exceed vega budget (${round(vega_budget - vega_used, 0)} left)"})
                continue
            budget_left -= con["max_loss_total"]
            vega_used += con_vega
            built.append(con)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "enabled": self.enabled(),
            "candidates": len(cands), "open_positions": len(open_syms),
            "free_slots": slots, "planned": built, "skipped": skipped[:20],
            "cap_per_position_usd": self.MAX_LOSS_PER_POSITION_USD,
            "total_defined_risk_usd": round(sum(b["max_loss_total"] for b in built), 2),
            "vega_budget_usd": round(vega_budget, 1),
            "vega_deployed_usd": round(vega_used, 1),
            "total_new_vega_usd": round(sum(abs(self._f(b.get("net_vega"))) for b in built), 1),
            # This plan is RE-PRICED off live option quotes on every call — two calls a minute apart return
            # different max-loss/credit dollars. Mark it point-in-time so a consumer can't quote it as a
            # constant, and so it reads consistently with the cached Best Iron Condors surface.
            "point_in_time": True,
            "precision": ("figures rebuilt from live option quotes each call — ± / vary run-to-run, "
                          "never a fixed constant"),
            "status": "VRP_SHORT_PREMIUM_PLAN",
        }

    # ------------------------------------------------------------ booking (GATED)

    def _booking(self):
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        return TradeStationSimBookingEngine()

    @staticmethod
    def _alert_condor_close_failed(row, leg_results, atomic=False, reject_reason=None):
        """External alert when a condor close did not fully confirm. The two cases are NOT the same risk:
        ATOMIC (all-or-none) → a reject closes NOTHING, so the full defined-risk condor is INTACT, NOT
        unhedged → WARNING, retries on its own. LEGACY leg-by-leg → a partial CAN leave a naked short →
        CRITICAL, check the position now."""
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            sym = row.get("symbol")
            if atomic:
                eng.dispatch(
                    title="GreyLine condor close rejected — condor INTACT",
                    message=(f"{sym} atomic condor close was rejected ({reject_reason or 'no reason given'}). "
                             "All-or-none, so NOTHING closed — the FULL condor is still open, defined-risk, "
                             "NOT unhedged. The manager retries each cycle."),
                    severity="WARNING", fingerprint=f"CONDOR_CLOSE_REJECTED:{sym}")
            else:
                failed = [lr["symbol"] for lr in leg_results if not lr["ok"]]
                eng.dispatch(
                    title="GreyLine condor close UNCONFIRMED — possible unhedged leg",
                    message=(f"{sym} condor close did not fully confirm; unconfirmed leg(s): "
                             f"{', '.join(failed) or 'n/a'}. Left OPEN (not marked CLOSED). The unit may "
                             "be partially closed / unhedged — check the position NOW."),
                    severity="CRITICAL", fingerprint=f"CONDOR_CLOSE_UNCONFIRMED:{sym}")
        except Exception:
            pass

    def _close_fill_debit(self, leg_results, fallback_debit, fallback_basis):
        """Net per-share debit ACTUALLY paid to close, from broker fills. Returns (debit, basis).

        Reads REAL fills for BOTH close paths → basis 'fills':
          * ATOMIC: all legs share one order id; the order carries a Legs[] array with per-leg
            `ExecutionPrice`, signed by `BuyOrSell` (Buy=pay to buy back a short, Sell=receive to sell a
            wing). Shape confirmed from live SIM order history (2026-07-31 capture).
          * LEGACY: one order per leg; sum each leg's FilledPrice signed by the close action.
        Every leg must have a POSITIVE execution price, else it returns the caller's conservative
        marketable close-order debit (basis 'close_order'/'mid') — so a not-yet-populated fill can never
        fabricate a number. Best-effort — never raises, never blocks a confirmed close."""
        oids = [str(lr.get("order_id")) for lr in leg_results if lr.get("order_id")]
        if not oids:
            return fallback_debit, fallback_basis
        try:
            orders = {str(o.get("OrderID")): o for o in
                      ((self._booking().orders().get("response_json") or {}).get("Orders") or [])}
        except Exception:
            return fallback_debit, fallback_basis

        # ATOMIC — one shared order id; read per-leg ExecutionPrice from its Legs[]. Require a FULL fill,
        # not just a positive price: the order must be Filled AND every leg's ExecQuantity must match its
        # QuantityOrdered — else a PARTIAL fill (positive ExecutionPrice on under-filled legs) would be
        # mislabeled basis 'fills' and priced on the full quantity. Any shortfall → conservative fallback.
        if len(set(oids)) == 1:
            o = orders.get(oids[0])
            legs = (o or {}).get("Legs") or []
            if o and str(o.get("StatusDescription")) in ("Filled", "FLL") and len(legs) == len(leg_results):
                debit = 0.0
                for lg in legs:
                    fp = self._f(lg.get("ExecutionPrice"))
                    exq, ordq = self._f(lg.get("ExecQuantity")), self._f(lg.get("QuantityOrdered"))
                    if fp <= 0 or ordq <= 0 or exq < ordq:            # unfilled or PARTIAL leg
                        return fallback_debit, fallback_basis
                    debit += fp if str(lg.get("BuyOrSell")).upper() == "BUY" else -fp
                return round(debit, 4), "fills"
            return fallback_debit, fallback_basis

        # LEGACY — one order per leg; sum FilledPrice signed by the close action
        debit, found = 0.0, 0
        for lr in leg_results:
            o = orders.get(str(lr.get("order_id")))
            if not o or str(o.get("StatusDescription")) not in ("Filled", "FLL"):
                continue
            fp = self._f(o.get("FilledPrice")) or self._f(((o.get("Legs") or [{}])[0]).get("ExecutionPrice"))
            if fp <= 0:
                continue
            debit += fp if lr.get("action") == "BUYTOCLOSE" else -fp   # pay to buy back, receive to sell wing
            found += 1
        if found == len(leg_results) and found > 0:
            return round(debit, 4), "fills"
        return fallback_debit, fallback_basis

    def _place_condor_open(self, con, b):
        """Place ONE condor's four opening legs. ATOMIC multi-leg (all-or-none, no naked-leg window)
        when GREYLINE_CONDOR_ATOMIC_ORDER is on; else LEGACY wings-first legging (reconciler backstops).
        Returns (placed_legs, error) — error is None on success, or a dict for the caller's error list.
        Shared by BOTH the VRP and earnings-vol opens so they can't drift apart."""
        qty = con["quantity"]
        legs_spec = [("wing_call", "BUYTOOPEN"), ("wing_put", "BUYTOOPEN"),
                     ("short_call", "SELLTOOPEN"), ("short_put", "SELLTOOPEN")]
        if self._atomic_orders_enabled():
            ml_legs = [{"symbol": con["legs"][n]["symbol"], "quantity": qty, "action": a}
                       for n, a in legs_spec]
            net = self._tick_round(abs(self._f(con.get("credit_per_condor"))))
            r = b.place_multileg(ml_legs, order_type="Limit", limit_price=net, tif="DAY")
            if r.get("ok"):
                return ([{"symbol": l["symbol"], "action": l["action"],
                          "order_id": r.get("order_id"), "atomic": True} for l in ml_legs], None)
            return (None, {"symbol": con["symbol"], "atomic": True,
                           "reject": r.get("reject_reason"), "http": r.get("http_status")})
        # LEGACY: wings FIRST so the tail cap exists before the shorts go live.
        placed = []
        for name, action in legs_spec:
            leg = con["legs"][name]
            px = leg["ask"] if action == "BUYTOOPEN" else leg["bid"]   # marketable limit
            r = b.place_order(leg["symbol"], qty, action=action, order_type="Limit",
                              limit_price=self._tick_round(px), tif="DAY")
            if r.get("ok"):
                placed.append({"symbol": leg["symbol"], "action": action,
                               "order_id": r.get("order_id"), "limit": self._tick_round(px)})
            else:
                return (None, {"symbol": leg["symbol"], "http": r.get("http_status")})
        return (placed, None)

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
            placed_legs, err = self._place_condor_open(con, b)   # atomic-or-legacy (shared with earnings)
            if err is not None:
                errors.append(err)
                continue
            # PROVENANCE for later PROOF: an edge can only be validated if the conditions it was
            # sold under are recorded at entry. entry_iv_rank is the richness that IS the edge
            # (registry: VRP ~9.6x conditional on rich IV); dte_selection_mode + entry_dte let the
            # adaptive-vs-static tenor hypothesis be measured out-of-sample; skew ties to skew-timing.
            from app.services.adaptive_dte_selection_engine import AdaptiveDTESelectionEngine
            rec = {
                "symbol": con["symbol"], "quantity": qty, "expiration": con["expiration"],
                "legs": placed_legs, "credit_per_condor": con["credit_per_condor"],
                "credit_total": con["credit_total"], "max_loss_total": con["max_loss_total"],
                "opened_at": datetime.utcnow().isoformat(), "status": "OPEN",
                # --- provenance (added 2026-07-26 so the harvest is provable from real trades) ---
                "entry_dte": self._dte(con["expiration"]),
                "dte_selection_mode": "adaptive" if AdaptiveDTESelectionEngine.enabled() else "static",
                "entry_iv_rank": con.get("iv_rank"),
                "entry_iv": con.get("iv"),
                "entry_skew": con.get("skew"),
                "return_on_risk": con.get("return_on_risk"),
            }
            self.LEDGER.parent.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(rec) + "\n")
            opened.append({"symbol": con["symbol"], "qty": qty,
                           "credit": con["credit_total"], "max_loss": con["max_loss_total"]})
        return {"timestamp": datetime.utcnow().isoformat(), "opened": opened,
                "errors": errors, "status": "VRP_SHORT_PREMIUM_OPENED"}

    # ------------------------------------------------------------ exit doctrine

    def _short_leg_greeks_map(self, open_rows):
        """{option_symbol: |delta|} for every leg across open condors — live from the chain, one
        fetch per (underlying, expiry). Used by the gamma defense to see tested short strikes."""
        try:
            from app.services.portfolio_greeks_engine import PortfolioGreeksEngine
            pg = PortfolioGreeksEngine()
        except Exception:
            return {}
        groups, out = set(), {}
        for r in open_rows:
            for leg in r.get("legs", []):
                und, exp = pg._parse(leg.get("symbol"))
                if und and exp:
                    groups.add((und, exp))
        for und, exp in groups:
            for sym, g in (pg._chain_greeks(und, exp) or {}).items():
                out[sym] = abs(g.get("delta") or 0.0)
        return out

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
        # A condor CLOSE can only route during the regular session — after hours the broker rejects every
        # order "all routes are closed", which used to fire a scary CRITICAL each cycle for nothing. We
        # still EVALUATE exits after hours (so the operator sees what's due) but only PLACE them at the open.
        from app.services.market_hours_engine import MarketHoursEngine
        market_open = MarketHoursEngine().status().get("is_regular_session") is True

        # Pre-fetch current greeks once per (underlying, expiry) so the gamma defense can read each
        # short leg's LIVE delta without a chain call per position.
        greeks = self._short_leg_greeks_map([r for r in rows if r.get("status") == "OPEN"])

        decisions = []
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            # current cost to CLOSE the condor = pay to buy back shorts, receive to sell wings
            cost_to_close = 0.0
            priced = True
            leg_quotes = {}
            for leg in r["legs"]:
                qd = (q.get_quote(leg["symbol"]).get("response_json") or {})
                row = (qd.get("Quotes") or [qd])[0] if isinstance(qd, dict) else {}
                bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
                if bid <= 0 or ask <= 0:
                    priced = False
                    break
                leg_quotes[leg["symbol"]] = (bid, ask)     # retained to PRICE the exit, not market it
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

            # GAMMA DEFENSE: has a short leg been tested toward ITM? (live delta of the shorts)
            tested_delta = max((greeks.get(str(leg["symbol"]).upper(), 0.0)
                                for leg in r["legs"] if leg["action"] == "SELLTOOPEN"), default=0.0)

            reason = None
            if r.get("strategy") == "earnings_vol":
                # EARNINGS-VOL exit: the IV crush is realized within ~1 session of the report — close
                # then. The post-earnings weekly is intentionally short-dated, so MANAGE_DTE and the
                # gamma-defense exit do NOT apply (they'd close it the moment it opened).
                _today = datetime.utcnow().date().isoformat()
                _rd = str(r.get("report_date") or "")[:10]
                if pnl_per >= self.PROFIT_TAKE_FRAC * credit * 100:
                    reason = "EARNINGS_PROFIT_TAKE"
                elif _rd and _today > _rd:
                    reason = "EARNINGS_CRUSH_CAPTURED"
                elif pnl_total <= -self.HARD_STOP_LOSS_MULT * max_loss_total:
                    reason = "HARD_STOP_NEAR_MAX_LOSS"
            elif pnl_per >= self.PROFIT_TAKE_FRAC * credit * 100:
                reason = "PROFIT_TAKE_50PCT"
            elif tested_delta >= self.TESTED_SHORT_DELTA:
                reason = f"DEFEND_TESTED_STRIKE_{round(tested_delta, 2)}d"
            elif dte <= self.MANAGE_DTE:
                reason = f"MANAGE_DTE_{dte}D"
            elif pnl_total <= -self.HARD_STOP_LOSS_MULT * max_loss_total:
                reason = "HARD_STOP_NEAR_MAX_LOSS"
            if not reason:
                decisions.append({"symbol": r["symbol"], "action": "HOLD",
                                  "pnl": round(pnl_total, 2), "dte": dte})
                continue

            committed = False
            if self.enabled() and not dry_run and not market_open:
                # A close was decided but the MARKET IS CLOSED — placing now just rejects ("all routes are
                # closed") and pages the operator for nothing. Defer to the open; the manager re-fires each
                # cycle and will place it during the regular session. No order, no alert.
                r["manager_status"] = "VRP_CONDOR_CLOSE_DEFERRED"
                r["manager_status_reason"] = f"{reason} — market closed, will place at the open"
            elif self.enabled() and not dry_run:
                b = self._booking()
                if self._atomic_orders_enabled():
                    # ATOMIC CLOSE: one multi-leg order — all legs close together or none. A partial/naked
                    # close is impossible; worst case it doesn't fill and the FULL (defined-risk) condor
                    # stays open. Priced at the marketable net debit (pay ask to buy back shorts, receive
                    # bid to sell wings) so it fills.
                    close_legs, mk_debit = [], 0.0
                    for lg in r["legs"]:
                        ca = "BUYTOCLOSE" if lg["action"] == "SELLTOOPEN" else "SELLTOCLOSE"
                        close_legs.append({"symbol": lg["symbol"], "quantity": r["quantity"], "action": ca})
                        bid, ask = leg_quotes.get(lg["symbol"], (0.0, 0.0))
                        mk_debit += (ask if ca == "BUYTOCLOSE" else -bid)
                    res = b.place_multileg(close_legs, order_type="Limit",
                                           limit_price=self._tick_round(abs(mk_debit)), tif="DAY")
                    all_ok = bool(res.get("ok"))
                    leg_results = [{"symbol": l["symbol"], "action": l["action"], "ok": all_ok,
                                    "order_id": res.get("order_id"), "atomic": True, "status": res.get("status"),
                                    "reject_reason": res.get("reject_reason")}
                                   for l in close_legs]
                    # realized is priced at the MARKETABLE close debit we transacted at (not mid) — a real,
                    # conservative number (the fill is at-or-better). No mid optimism, no haircut fudge.
                    close_debit, close_basis = mk_debit, "close_order"
                else:
                    # LEGACY leg-by-leg: close SHORTS first (BUYTOCLOSE), then wings (SELLTOCLOSE). If a short
                    # buyback fails we have NOT yet sold its protective wing, so an out-of-order partial can't
                    # manufacture a naked short. A MARKETABLE LIMIT caps the price; a rejected leg reports ok=False.
                    # (Note: ok = order ACCEPTED, not filled — a marketable limit that doesn't fill can still
                    # leave the unit unhedged; the atomic path above closes that gap. Reconciler backstops it.)
                    legs_ordered = sorted(r["legs"], key=lambda lg: 0 if lg["action"] == "SELLTOOPEN" else 1)
                    leg_results, all_ok = [], True
                    close_debit, _od_ok = 0.0, True   # marketable close debit; falls back to mid if a leg markets
                    for leg in legs_ordered:
                        close_action = "BUYTOCLOSE" if leg["action"] == "SELLTOOPEN" else "SELLTOCLOSE"
                        bid, ask = leg_quotes.get(leg["symbol"], (0.0, 0.0))
                        if bid > 0 and ask > 0:
                            px = ask if close_action == "BUYTOCLOSE" else bid
                            close_debit += px if close_action == "BUYTOCLOSE" else -px
                            res = b.place_order(leg["symbol"], r["quantity"], action=close_action,
                                                order_type="Limit", limit_price=self._tick_round(px), tif="DAY")
                        else:
                            _od_ok = False                                       # no quote -> can't price this leg
                            res = b.place_order(leg["symbol"], r["quantity"], action=close_action,
                                                order_type="Market", tif="DAY")   # no usable quote: fallback
                        ok_leg = bool(res.get("ok"))
                        all_ok = all_ok and ok_leg
                        leg_results.append({"symbol": leg["symbol"], "action": close_action, "ok": ok_leg,
                                            "status": res.get("status"), "order_id": res.get("order_id")})
                    close_basis = "close_order" if _od_ok else "mid"
                    if not _od_ok:
                        close_debit = cost_to_close                              # a leg had no quote -> mid mark
                r.setdefault("close_attempts", []).append(
                    {"at": datetime.utcnow().isoformat(), "reason": reason, "legs": leg_results, "all_ok": all_ok})
                if all_ok:
                    # Every leg confirmed at the broker — only NOW is the unit truly flat. Marking CLOSED
                    # or banking realized before this would be fantasy P&L on a still-live position.
                    # Realized P&L is priced from the ACTUAL close fills when readable (legacy per-leg), else
                    # the marketable close-order debit — NOT mid. So the edge court gets an honest number
                    # with no haircut fudge. See _close_fill_debit + EdgePersistenceEngine basis handling.
                    debit, basis = self._close_fill_debit(leg_results, close_debit, close_basis)
                    r["status"] = "CLOSED"; r["closed_at"] = datetime.utcnow().isoformat()
                    r["close_reason"] = reason
                    r["realized_pnl"] = round((credit - debit) * 100 * r["quantity"], 2)
                    r["realized_pnl_basis"] = basis
                    # measured CLOSE-side execution slippage (net debit paid vs the net mid) → ExecutionLog,
                    # ONLY on a CONFIRMED fill (basis == 'fills'). On order ACCEPTANCE the debit is the
                    # marketable-limit ESTIMATE (basis 'close_order') — logging that would feed ExecutionLog a
                    # fill that never happened, so we skip it (the realized_pnl still records, honestly labeled).
                    if basis == "fills":
                        try:
                            from app.services.execution_log_engine import ExecutionLogEngine
                            _sleeve = "premium_earnings" if str(r.get("strategy")) == "earnings_vol" else "premium_vrp"
                            ExecutionLogEngine().record_fill(_sleeve, r["symbol"], "BUY",
                                                             int(r["quantity"]) * 100, mid=cost_to_close, fill=debit)
                        except Exception:
                            pass
                    r.pop("manager_status", None); r.pop("manager_status_reason", None)
                    committed = True
                elif any(lr.get("atomic") for lr in leg_results):
                    # ATOMIC close (all-or-none) rejected → NOTHING closed → the FULL condor is intact and
                    # defined-risk, NOT unhedged. Surface it (the defensive exit didn't execute) but don't
                    # cry "unhedged"; the manager retries next cycle.
                    rr = next((lr.get("reject_reason") for lr in leg_results if lr.get("reject_reason")), None)
                    r["manager_status"] = "VRP_CONDOR_CLOSE_REJECTED_INTACT"
                    r["manager_status_reason"] = (f"atomic close rejected ({rr or 'no reason'}) — full condor "
                                                  "intact (defined-risk), NOT unhedged; retrying next cycle")
                    self._alert_condor_close_failed(r, leg_results, atomic=True, reject_reason=rr)
                else:
                    # LEGACY leg-by-leg partial: some legs may have closed, some not → possibly UNHEDGED.
                    # Never mark CLOSED on a partial. Leave OPEN, flag it, alert — this must be surfaced.
                    closed_n = sum(1 for lr in leg_results if lr["ok"])
                    r["manager_status"] = "VRP_CONDOR_CLOSE_UNCONFIRMED"
                    r["manager_status_reason"] = (f"{closed_n}/{len(leg_results)} legs confirmed — "
                                                  "position may be unhedged")
                    self._alert_condor_close_failed(r, leg_results, atomic=False)
            decisions.append({"symbol": r["symbol"], "action": "CLOSE", "reason": reason,
                              "committed": committed, "pnl": round(pnl_total, 2), "dte": dte})

        if self.enabled() and not dry_run and any(d["action"] == "CLOSE" for d in decisions):
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        return {"timestamp": datetime.utcnow().isoformat(),
                "managed": len(decisions), "decisions": decisions,
                "acted": bool(self.enabled() and not dry_run), "status": "VRP_SHORT_PREMIUM_MANAGED"}

    def open_condor_exits(self):
        """READ-ONLY exit levels for every OPEN condor — the price targets the exit doctrine acts on.
        Expressed as NET BUYBACK cost (what you pay to close): profit-take fires when the buyback falls
        to (1-frac)*credit; the hard-stop fires when it rises to credit + mult*max_loss. Levels are read
        straight from the ledger. Also attaches a best-effort per-condor unrealized P&L (and % return on
        the defined max loss) from a SINGLE broker positions read — null if the read fails, so the static
        exit levels always render. No orders."""
        try:
            rows = [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return {"timestamp": datetime.utcnow().isoformat(), "condors": [], "status": "NO_VRP_LEDGER"}

        # Best-effort LIVE P&L per condor from ONE broker positions read (the broker's marks) — cheaper and
        # steadier than re-quoting every leg. P/L = credit + Σ(current leg MarketValues) (a short leg's MV is
        # negative), i.e. credit − current cost-to-close. Empty/None on a failed read → P/L renders "—".
        marks = {}
        try:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            for p in ((TradeStationSimBookingEngine().positions().get("response_json") or {}).get("Positions") or []):
                marks[str(p.get("symbol") or p.get("Symbol") or "").upper()] = self._f(p.get("MarketValue"))
        except Exception:
            marks = {}

        out = []
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            cr, ml = self._f(r.get("credit_total")), self._f(r.get("max_loss_total"))
            strat = r.get("strategy") or "vrp"
            dte = self._dte(r.get("expiration"))
            time_exit = (f"~1 session after {r.get('report_date')} report (IV crush)"
                         if strat == "earnings_vol" else f"liquidate at DTE ≤ {self.MANAGE_DTE}")
            legsyms = [str(lg.get("symbol") or "").upper() for lg in (r.get("legs") or [])]
            pnl = pnl_pct = None
            if marks and legsyms and all(s in marks for s in legsyms):
                pnl = round(cr + sum(marks[s] for s in legsyms), 2)          # credit − current cost-to-close
                pnl_pct = round(pnl / ml * 100, 1) if ml else None           # return on the defined max loss
            out.append({
                "symbol": r.get("symbol"), "strategy": strat, "expiration": r.get("expiration"),
                "dte": dte, "quantity": r.get("quantity"),
                "credit_total": round(cr, 2), "max_loss_total": round(ml, 2),
                "pnl": pnl, "pnl_pct": pnl_pct,
                "profit_take_buyback": round(cr * (1 - self.PROFIT_TAKE_FRAC), 2),
                "profit_take_lock": round(cr * self.PROFIT_TAKE_FRAC, 2),
                "hard_stop_buyback": round(cr + self.HARD_STOP_LOSS_MULT * ml, 2),
                "hard_stop_loss": round(self.HARD_STOP_LOSS_MULT * ml, 2),
                "time_exit": time_exit,
            })
        out.sort(key=lambda c: c["dte"] if c.get("dte") is not None else 999)
        return {
            "timestamp": datetime.utcnow().isoformat(), "condors": out,
            "doctrine": {"profit_take_frac": self.PROFIT_TAKE_FRAC,
                         "hard_stop_loss_mult": self.HARD_STOP_LOSS_MULT, "manage_dte": self.MANAGE_DTE},
            "status": "CONDOR_EXITS",
        }

