"""Live managed-futures / time-series-momentum sleeve — the crisis-convex DIVERSIFIER.

Backtest GO (ManagedFuturesResearchEngine): net Sharpe ~0.41 full / 0.57 recent, POSITIVE in every
stress year (2008 +17%, 2020 +19%, 2022 +23%), and — the point — only +0.02 correlated to the carry
sleeve. The SHORT side is what decorrelates it: long/flat (like the trend sleeve) is ~+0.57 to carry,
long/short is ~+0.02. Held honestly as a forward-TEST until EdgePersistence confirms the live edge.

Mechanics (mirror the trend sleeve; conservative by design):
  * SIGNAL per asset: multi-horizon TSMOM — sign of trailing return over 63/126/252 trading days
    (CSV history + today's live quote as the latest close), blended to [-1, 1].
  * SIZE: inverse-vol (trailing 60d) weights, normalized so gross exposure = the sleeve budget
    (%-of-equity via SleeveCapitalBudgetEngine). Whole shares. MONTHLY rebalance cadence — the
    backtest showed weekly/daily turnover destroys the edge on cost.
  * SHORTS: the plan ALWAYS shows the real long/short target, but execution stays LONG/FLAT unless
    GREYLINE_MANAGED_FUTURES_ALLOW_SHORTS=true. Shorts wait on the place_order body-verification fix
    (a rejected short = naked exposure), so they are OFF until that lands and SELLSHORT is verified.
  * SOURCE OF TRUTH for held size is the LIVE broker position, never a ledger count.
Gated OFF by GREYLINE_MANAGED_FUTURES_ENABLED — it does not arm itself, and with a 0% budget
(default) it holds nothing even if enabled.
"""

import csv
import math
from datetime import datetime
from os import getenv
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


class ManagedFuturesEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/managed_futures")
    # Whole-share-affordable ETFs spanning the asset classes the research validated. Cheaper share
    # classes of the same indices where they exist (QQQM~Nasdaq, GLDM~gold) so a $10k book can hold
    # whole shares. The TSMOM method is identical to the research (which used index-level SPY/GLD).
    BASKET = ["QQQM", "IWM", "EFA", "EEM", "TLT", "IEF", "GLDM", "SLV", "DBC", "DBA"]
    LOOKBACKS = [63, 126, 252]
    VOL_WIN = 60
    TARGET_VOL = 0.10
    TRADING_DAYS = 252
    REBALANCE_MIN_USD = 100.0

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_MANAGED_FUTURES_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def allow_shorts():
        return (getenv("GREYLINE_MANAGED_FUTURES_ALLOW_SHORTS", "") or "").strip().lower() == "true"

    @classmethod
    def _budget(cls):
        # %-of-equity budget (0 until GREYLINE_MANAGED_FUTURES_ALLOC_PCT is set). Clamped to cash.
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            return SleeveCapitalBudgetEngine.budget_usd("managed_futures")
        except Exception:
            return 0.0

    def _closes(self, sym):
        out = {}
        try:
            with open(self.HIST / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c > 0:
                        out[str(r.get("date"))[:10]] = c
        except Exception:
            return {}
        return out

    def _quote(self, q, sym):
        rj = (q.get_quote(sym).get("response_json") or {})
        row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
        return self._f(row.get("Bid")), self._f(row.get("Ask")), self._f(row.get("Last") or row.get("Close"))

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    MAX_STALE_DAYS = 4          # allow a 3-day holiday weekend; beyond it the daily refresh has stalled

    def _signal(self, sym, live_last):
        """Blended multi-horizon TSMOM sign in [-1,1] + trailing annualized vol, using CSV history
        plus today's live price as the latest close. None if history is too short; {"stale": reason}
        when the newest bar is too old to trade on (a stalled refresh must not TSMOM on stale bars)."""
        closes = self._closes(sym)
        if len(closes) < max(self.LOOKBACKS) + 2:
            return None
        ds = sorted(closes)
        try:
            age = (datetime.utcnow().date() - datetime.fromisoformat(ds[-1]).date()).days
            if age > self.MAX_STALE_DAYS:
                return {"stale": f"newest bar {ds[-1]} is {age} calendar days old (max {self.MAX_STALE_DAYS})"}
        except (ValueError, TypeError):
            return {"stale": f"unusable newest bar date {ds[-1]!r}"}
        series = [closes[d] for d in ds]
        last = live_last if live_last > 0 else series[-1]
        series = series[:-1] + [last] if live_last > 0 else series      # today's price as latest
        sg = 0.0
        for L in self.LOOKBACKS:
            sg += 1.0 if series[-1] > series[-1 - L] else -1.0
        blend = sg / len(self.LOOKBACKS)
        rets = [series[i] / series[i - 1] - 1 for i in range(max(1, len(series) - self.VOL_WIN), len(series))]
        vol = max(self._stdev(rets) * math.sqrt(self.TRADING_DAYS), 0.05)
        return {"blend": blend, "vol": round(vol, 4), "last": round(last, 2)}

    def _held(self, pos_engine, sym):
        rj = (pos_engine.get_positions().get("response_json") or {})
        for p in (rj.get("Positions") or []):
            if str(p.get("Symbol")).upper() == sym and p.get("AssetType") == "STOCK":
                return int(self._f(p.get("Quantity")))
        return 0

    def plan(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
        q = TradeStationQuoteLiveEngine()
        pos = TradeStationPositionsLiveEngine()
        budget = self._budget()
        shorts = self.allow_shorts()

        sigs, pxs, stale_syms = {}, {}, []
        for sym in self.BASKET:
            bid, ask, last = self._quote(q, sym)
            sig = self._signal(sym, last)
            if sig is None:
                continue
            if sig.get("stale"):
                # Never TSMOM on stale bars — skip this symbol (no target; existing position untouched).
                stale_syms.append(sym)
                continue
            px = last or ask or bid
            if px <= 0:
                continue
            sigs[sym] = {**sig, "bid": bid, "ask": ask, "px": px}
            pxs[sym] = px

        # inverse-vol raw weights; normalize so gross exposure == budget
        raw = {s: sigs[s]["blend"] / sigs[s]["vol"] for s in sigs}
        gross = sum(abs(w) for w in raw.values()) or 1.0
        legs, deployed = [], 0.0
        for sym in self.BASKET:
            if sym not in sigs:
                legs.append({"symbol": sym, "skipped": ("STALE_DATA" if sym in stale_syms
                                                        else "insufficient history / no quote")})
                continue
            s = sigs[sym]
            notional_signed = budget * raw[sym] / gross                 # real long/short target $
            notional_exec = notional_signed if shorts else max(0.0, notional_signed)  # long/flat unless armed
            tgt_signed = int(notional_signed / s["px"]) if s["px"] else 0
            tgt_exec = int(notional_exec / s["px"]) if s["px"] else 0
            held = self._held(pos, sym)
            deployed += abs(tgt_exec) * s["px"]
            legs.append({
                "symbol": sym, "blend": s["blend"], "vol": s["vol"], "last": s["last"],
                "bid": s["bid"], "ask": s["ask"], "held": held,
                "target_shares_signed": tgt_signed,        # the real long/short signal
                "target_shares": tgt_exec,                 # what will execute (long/flat unless shorts armed)
                "delta_shares": tgt_exec - held,
                "delta_usd": round((tgt_exec - held) * s["px"], 2),
                # direction reflects the SIGNAL (blend), not the funding — so an unfunded/0-budget
                # sleeve still honestly shows which names it would long vs short.
                "direction": ("LONG" if s["blend"] > 0 else "SHORT" if s["blend"] < 0 else "FLAT"),
            })
        return {
            "status": "MF_PLAN", "armed": self.enabled(), "shorts_execute": shorts,
            "budget_usd": round(budget, 2), "deployed_usd": round(deployed, 2),
            "note": ("budget is 0 — set GREYLINE_MANAGED_FUTURES_ALLOC_PCT to fund" if budget <= 0
                     else "long/flat execution; short targets shown but not traded until "
                          "GREYLINE_MANAGED_FUTURES_ALLOW_SHORTS=true" if not shorts else "long/short"),
            "legs": legs,
        }

    # ---- monthly cadence -----------------------------------------------------------------------

    def _et_month(self):
        try:
            return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m") if ZoneInfo else None
        except Exception:
            return None

    def _last_month(self):
        try:
            return (self.STATE / "last_rebalance_month.txt").read_text().strip()
        except Exception:
            return None

    def _mark_month(self, m):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            (self.STATE / "last_rebalance_month.txt").write_text(m or "")
        except Exception:
            pass

    def due(self):
        """Monthly cadence: rebalance once per calendar month (ET). None ET date => not due (safe)."""
        m = self._et_month()
        if not m:
            return False, None
        return (m != self._last_month()), m

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "MF_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "MF_MARKET_CLOSED", "acted": False}
        due, month = self.due()
        if not due and not dry_run:
            return {"status": "MF_NOT_DUE", "acted": False, "cadence": "monthly", "month": month}
        p = self.plan()
        # make this sleeve's fills VISIBLE to the edge court (books straight to the broker). Broker-
        # confirmed FIFO; the empty-read guard makes it safe on a degraded positions read.
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            SleeveTradeLedgerEngine().reconcile_plan("managed_futures", p.get("legs"))
        except Exception:
            pass
        if p["budget_usd"] <= 0:
            return {"status": "MF_UNFUNDED", "acted": False, **{"note": p["note"]}}

        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        from app.services.execution_pricing_engine import ExecutionPricingEngine
        book = TradeStationSimBookingEngine()
        acts = []
        for leg in p["legs"]:
            d = leg.get("delta_shares")
            if not d:
                continue
            if d > 0 and abs(leg["delta_usd"]) < self.REBALANCE_MIN_USD:
                continue                                    # entries respect a churn threshold; sells always act
            action = "BUY" if d > 0 else "SELL"             # long/flat only (shorts gated out of target_shares)
            limit = ExecutionPricingEngine.patient_limit(leg["bid"], leg["ask"], d > 0)
            if not limit or limit <= 0:
                continue
            if dry_run:
                acts.append({"symbol": leg["symbol"], "would": action, "qty": abs(d), "limit": limit})
                continue
            if action == "SELL":
                try:
                    from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                    BrokerProtectiveStopEngine().clear_stop(leg["symbol"])
                except Exception:
                    pass
            r = book.place_order(leg["symbol"], abs(d), action=action, order_type="Limit",
                                 limit_price=limit, tif="DAY")
            try:
                from app.services.execution_log_engine import ExecutionLogEngine
                ExecutionLogEngine().record("managed_futures", leg["symbol"], action, d, limit,
                                            leg["bid"], leg["ask"], r.get("order_id"))
            except Exception:
                pass
            acts.append({"symbol": leg["symbol"], "action": action, "qty": abs(d), "limit": limit,
                         "ok": r.get("ok"), "order_id": r.get("order_id")})
        if not dry_run:
            self._mark_month(month)
        return {"status": "MF_REBALANCED" if not dry_run else "MF_DRYRUN",
                "acted": bool(acts and not dry_run), "month": month,
                "deployed_usd": p["deployed_usd"], "actions": acts}

    def status(self):
        due, month = self.due()
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(),
                "shorts_execute": self.allow_shorts(), "due_this_month": due, "month": month,
                **self.plan()}
