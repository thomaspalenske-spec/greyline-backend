"""Central sleeve capital budget — %-of-equity, not fixed dollars.

WHY THIS EXISTS: the six sleeves used to each spend a private, STATIC dollar allocation
(trend $2,217, carry $1,583, momentum $2,000, VRP $1,200, earnings $900). Two problems the
operator called out:
  1. Fixed dollars DON'T scale with the account — a book that compounds to $15k still only
     ever deployed ~$7,900; the rest sat idle. Caps should be a PERCENT of live equity.
  2. Their sum (79% of the book) capped total deployment below 100% — cash was stranded in
     T-bills even when sleeves had opportunities. The book should be able to put up to 100%
     of available cash to work when the sleeves want it.

THIS ENGINE is the single resolver every sleeve now asks for its dollar budget:
    budget = pct_of_equity(sleeve) * current_mission_equity      (scales with the account)
    ... clamped to live DEPLOYABLE CASH so no single sleeve can over-commit the book.

Default percentages preserve the operator's existing RELATIVE balance (trend heaviest). They are
env-overridable (GREYLINE_<SLEEVE>_ALLOC_PCT) — this engine only reads knobs, it never trades.

CURRENT TARGET SUM: 97% of equity (momentum 25 + trend 28 + vol_carry 20 + low_vol 12 +
xs_momentum 12; vrp/earnings/managed_futures 0). This is NOT a full-100% deployment: ~3%
(~$300 on a $10k book) is left as deliberate unallocated headroom. That 3% is the residue of the
2026-08-04 VRP+earnings retirement (−27%) partly backfilled by low_vol (+12%) and xs_momentum
(+12%); the operator elected (2026-08-11) to KEEP the small buffer rather than redeploy it to 100%,
prudent while every sleeve's edge is still unproven and one over-deployment incident (2026-08-06)
is on the record.

SAFETY POSTURE: the sleeve sum is a SOFT target — the hard limiter is the per-sleeve clamp to live
DEPLOYABLE CASH (a sleeve never claims more than the book actually has free), backstopped by the
BookDeploymentCap (1.15× base) and the daily-loss governor (warn -4% / halt -7%, MONITOR+ALERT).
So the 3% headroom is a target ceiling, not a reserved cash lockbox.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path
from time import time


class SleeveCapitalBudgetEngine:

    # Default targets as PERCENT of live mission equity. The 8 tracked sleeves are momentum 25,
    # trend 28, vol_carry 20, vrp 0, earnings 0, low_vol 12, xs_momentum 12, managed_futures 0 ->
    # they sum to 97, leaving a deliberate ~3% unallocated cash buffer (not fully deployed).
    # managed_futures defaults to 0 (funded via GREYLINE_MANAGED_FUTURES_ALLOC_PCT when armed);
    # when it's funded, another sleeve is reduced to keep the live sum <= 100 (2026-07-30: it
    # REPLACED trend — trend set to 0% + disabled).
    DEFAULT_PCT = {
        "momentum": 25.0,
        "trend": 28.0,
        "vol_carry": 20.0,
        # VRP + earnings condor sleeves RETIRED (2026-08-04): the SIM can't price atomic condor closes,
        # so they can't produce trustworthy court data here. 0% until/unless re-armed. Their old 27%
        # slot went to the low-vol/BAB replacement (12%) plus idle headroom.
        "vrp": 0.0,
        "earnings": 0.0,
        "low_vol": 12.0,
        "xs_momentum": 12.0,     # cross-sectional dual-momentum ETF sleeve (forward-test candidate)
        "managed_futures": 0.0,
    }
    # Aliases so callers can use either name for the carry sleeve.
    _ALIAS = {"carry": "vol_carry"}

    # Fallback dollar budgets if BOTH the env pct and the equity read are unavailable (never trade
    # on a mystery number). These mirror the pre-conversion static caps.
    _FALLBACK_USD = {
        "momentum": 2000.0, "trend": 2217.0, "vol_carry": 1583.0, "vrp": 1200.0, "earnings": 900.0,
        "low_vol": 2000.0, "xs_momentum": 1500.0,
    }
    DEFAULT_BASE_USD = 10000.0
    _CACHE_TTL_S = 5.0            # coalesce the equity/cash reads across sleeves within one cycle

    _cache = {"t": 0.0, "equity": None, "cash": None}

    # ---- knobs ---------------------------------------------------------------------------------

    @classmethod
    def _canon(cls, sleeve):
        s = (sleeve or "").strip().lower()
        return cls._ALIAS.get(s, s)

    # Reversible pct overrides written by the evidence-driven auto-apply (SleeveBudgetAutoApplyEngine).
    # Precedence: an explicit operator env pin ALWAYS wins; else an auto-applied override beats the static
    # default; else the default. Clearing this file fully reverts the book — the auto-apply never touches
    # .env, so it can't trip the env-precedence trap.
    OVERRIDE_FILE = Path("app/data/state/sleeve_pct_overrides.json")

    @classmethod
    def _overrides(cls):
        try:
            d = json.loads(cls.OVERRIDE_FILE.read_text())
            return {cls._canon(k): float(v) for k, v in (d.get("pct") or {}).items()}
        except Exception:
            return {}

    # Crisis-diversifier floors: a sleeve here is never de-risked below this %-of-equity even under
    # risk-parity — vol_carry (short-vol) is a DIFFERENT-crash diversifier, so de-concentrating it must not
    # zero it. Override per-sleeve with GREYLINE_<SLEEVE>_RISK_FLOOR_PCT.
    RISK_FLOOR_PCT = {"vol_carry": 5.0}

    @classmethod
    def _risk_floor(cls, sleeve):
        s = cls._canon(sleeve)
        raw = getenv("GREYLINE_%s_RISK_FLOOR_PCT" % s.upper(), "")
        try:
            if str(raw).strip():
                return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
        return cls.RISK_FLOOR_PCT.get(s, 0.0)

    @classmethod
    def _risk_trim(cls):
        """The stepped, floored, DOWN-ONLY risk-concentration overrides written by
        SleeveBudgetAutoApplyEngine (override file 'risk_trim' map) — the glide that de-risks an
        over-concentrated sleeve toward risk-parity. Read-only; empty if none/unreadable."""
        try:
            d = json.loads(cls.OVERRIDE_FILE.read_text())
            return {cls._canon(k): float(v) for k, v in (d.get("risk_trim") or {}).items()}
        except Exception:
            return {}

    @classmethod
    def pct(cls, sleeve):
        """Target percent-of-equity for a sleeve. Precedence: explicit env pin
        (GREYLINE_<SLEEVE>_ALLOC_PCT) — but when risk-budget mode is on, a stepped DOWN-ONLY risk-trim may
        still de-risk a pinned concentration hog toward risk-parity (never raise a pin) > risk-budget re-mix
        of non-pinned armed sleeves to floored risk-parity > auto-applied override file > static default."""
        s = cls._canon(sleeve)
        if cls._env_pinned(s):                      # explicit operator env pin is the CEILING
            pin = cls._static_pct(s)
            if cls._risk_budget_on():
                trim = cls._risk_trim().get(s)      # pin reconciliation: a risk-trim may pull it DOWN only
                if trim is not None and trim < pin:
                    return max(0.0, min(100.0, trim))
            return pin
        if cls._risk_budget_on():                   # gated: size non-pinned armed sleeves to floored risk parity
            rp = cls._risk_parity_table().get(s)
            if rp is not None:
                return max(0.0, min(100.0, max(rp, cls._risk_floor(s))))
        return cls._static_pct(s)

    # ---- RISK-BUDGETED sizing (inverse-vol across sleeves) --------------------------------------
    # A fixed %-of-equity gives each sleeve equal CAPITAL, not equal RISK: a short-vol sleeve (SVXY carry)
    # at 20% carries far more book risk per dollar than a low-vol ETF sleeve at 12%, so the book is quietly
    # short-vol-concentrated (the exact imbalance the 24yr VRP tail work underlines). Risk-budgeting sizes
    # each sleeve inversely to its own realized vol so risk contributions equalize, re-mixed WITHIN the
    # same total deployment (not more leverage). ADVISORY by default (surfaced, changes nothing); live
    # application is gated GREYLINE_SLEEVE_RISK_BUDGET and only re-mixes NON-env-pinned armed sleeves.
    _HIST = Path("app/data/historical")
    _RISK_LOOKBACK = 252
    _rp_cache = {"t": 0.0, "table": None}

    @classmethod
    def _sleeve_instruments(cls, sleeve):
        """The traded basket for a sleeve — read from the sleeve engine so it can't go stale."""
        s = cls._canon(sleeve)
        try:
            if s == "vol_carry":
                from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine as E
                return [getattr(E, "SYMBOL", "SVXY")]
            if s == "low_vol":
                from app.services.low_volatility_engine import LowVolatilityEngine as E
                return list(E.BASKET)
            if s == "trend":
                from app.services.trend_following_engine import TrendFollowingEngine as E
                return list(E.BASKET)
            if s == "xs_momentum":
                from app.services.cross_sectional_momentum_engine import CrossSectionalMomentumEngine as E
                return list(E.UNIVERSE)
        except Exception:
            pass
        return {"vol_carry": ["SVXY"], "low_vol": ["USMV", "SPLV", "EFAV", "XMLV"],
                "trend": ["QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"],
                "xs_momentum": ["QQQM", "IWM", "EFA", "EEM", "TLT", "IEF", "HYG", "GLDM", "DBC", "VNQ"]
                }.get(s, [])

    @classmethod
    def _basket_returns(cls, symbols):
        """EQUAL-WEIGHT daily return series [(date, ret), ...] over the FULL common history of `symbols`.
        The single source of truth for a sleeve's return stream — shared by the risk-budget vol calc and
        the sizing backtest so both see exactly the same series. Empty list on missing/unreadable data."""
        import csv
        series = {}
        for sym in symbols:
            try:
                closes = []
                with open(cls._HIST / f"{sym}_daily.csv") as f:
                    for r in csv.DictReader(f):
                        c = r.get("close")
                        try:
                            c = float(c)
                        except (TypeError, ValueError):
                            c = None
                        if c and c > 0:
                            closes.append((str(r.get("date"))[:10], c))
                closes.sort()
                series[sym] = {closes[i][0]: closes[i][1] / closes[i - 1][1] - 1 for i in range(1, len(closes))}
            except Exception:
                continue
        if not series:
            return []
        common = sorted(set.intersection(*[set(r.keys()) for r in series.values()]))
        return [(d, sum(series[sym][d] for sym in series) / len(series)) for d in common]

    @classmethod
    def _basket_vol(cls, symbols):
        """Annualized vol of the EQUAL-WEIGHT basket's daily returns over the trailing window (captures the
        sleeve's own internal diversification). None if the data is missing/too short."""
        import math
        window = cls._basket_returns(symbols)[-cls._RISK_LOOKBACK:]
        if len(window) < 30:
            return None
        vals = [r for _, r in window]
        m = sum(vals) / len(vals)
        var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
        return math.sqrt(var) * math.sqrt(252)

    @classmethod
    def _static_pct(cls, sleeve):
        """pct() WITHOUT the risk-budget branch — env pin > override > default. The base the advisory
        re-mixes and the fallback when risk-budget mode is off."""
        s = cls._canon(sleeve)
        raw = getenv("GREYLINE_%s_ALLOC_PCT" % s.upper(), "")
        if str(raw).strip():
            try:
                return max(0.0, min(100.0, float(raw)))
            except (TypeError, ValueError):
                pass
        ov = cls._overrides().get(s)
        if ov is not None:
            return max(0.0, min(100.0, ov))
        return max(0.0, min(100.0, cls.DEFAULT_PCT.get(s, 0.0)))

    @classmethod
    def _env_pinned(cls, sleeve):
        return bool(str(getenv("GREYLINE_%s_ALLOC_PCT" % cls._canon(sleeve).upper(), "")).strip())

    @classmethod
    def _risk_budget_on(cls):
        return (getenv("GREYLINE_SLEEVE_RISK_BUDGET", "") or "").strip().lower() == "true"

    @classmethod
    def risk_budget_advisory(cls):
        """What inverse-vol RISK-BUDGETING would do to the armed sleeves vs the current %-of-equity mix —
        the risk-concentration diagnostic + the risk-parity target, preserving total deployment."""
        armed = [s for s in cls.DEFAULT_PCT if cls._static_pct(s) > 0]
        cur = {s: cls._static_pct(s) for s in armed}
        vol = {}
        for s in armed:
            v = cls._basket_vol(cls._sleeve_instruments(s))
            if v:
                vol[s] = v
        measured = [s for s in armed if s in vol]
        # re-mix ONLY the measured sleeves' OWN combined budget among themselves — never steal the slot of
        # an unmeasured sleeve (e.g. disarmed single-name momentum, which has a default pct but no basket).
        total = sum(cur[s] for s in measured)
        if not measured or total <= 0:
            return {"status": "INSUFFICIENT_VOL_DATA", "armed": armed, "measured": measured}
        inv = {s: 1.0 / vol[s] for s in measured}
        wsum = sum(inv.values())
        rp = {s: round(inv[s] / wsum * total, 2) for s in measured}
        risk_raw = {s: cur[s] * vol[s] for s in measured}
        rsum = sum(risk_raw.values()) or 1e-9
        rows = {}
        for s in measured:
            rows[s] = {
                "current_pct": round(cur[s], 2),
                "vol_annual_pct": round(vol[s] * 100, 1),
                "current_risk_share_pct": round(risk_raw[s] / rsum * 100, 1),
                "risk_parity_pct": rp[s],
                "delta_pct": round(rp[s] - cur[s], 2),
                "env_pinned": cls._env_pinned(s),
            }
        top = max(rows, key=lambda s: rows[s]["current_risk_share_pct"])
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "RISK_BUDGET_ADVISORY",
            "mode_live": cls._risk_budget_on(),
            "total_armed_pct": round(total, 2),
            "sleeves": rows,
            "most_risk_concentrated": {"sleeve": top,
                                       "current_risk_share_pct": rows[top]["current_risk_share_pct"]},
            "note": ("Inverse-vol risk-budget vs current %%-of-equity, re-mixed within the SAME %.1f%% "
                     "total. current_risk_share shows how book RISK (pct x vol) is actually split today; "
                     "risk_parity_pct equalizes it. %s carries the most risk today. ADVISORY unless "
                     "GREYLINE_SLEEVE_RISK_BUDGET=true (then non-pinned armed sleeves size to risk_parity_pct)."
                     % (total, top)),
        }

    @classmethod
    def _risk_parity_table(cls):
        """Cached {sleeve: risk_parity_pct} for the live sizing branch (kept off pct()'s hot path)."""
        now = time()
        c = cls._rp_cache
        if c["table"] is not None and (now - c["t"]) < 60.0:
            return c["table"]
        adv = cls.risk_budget_advisory()
        table = ({s: adv["sleeves"][s]["risk_parity_pct"] for s in adv["sleeves"]}
                 if adv.get("status") == "RISK_BUDGET_ADVISORY" else {})
        cls._rp_cache = {"t": now, "table": table}
        return table

    @classmethod
    def pct_table(cls):
        return {s: cls.pct(s) for s in cls.DEFAULT_PCT}

    @classmethod
    def total_pct(cls):
        return round(sum(cls.pct_table().values()), 4)

    # ---- live inputs (cached briefly so sleeves in one cycle share one read) --------------------

    @classmethod
    def _base(cls):
        try:
            return float(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000") or cls.DEFAULT_BASE_USD)
        except (TypeError, ValueError):
            return cls.DEFAULT_BASE_USD

    @classmethod
    def _read_equity(cls):
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            eq = MissionRiskGovernorEngine().snapshot().get("mission_equity")
            if eq is not None:
                return float(eq)
        except Exception:
            pass
        return None

    @classmethod
    def _read_deployable_cash(cls, equity):
        """Deployable cash = equity minus AT-RISK (non-SGOV) market value. SGOV is cash-equivalent
        (the sweep sells it back on demand), so it counts as deployable, not as committed risk.
        This mirrors /account-summary's cash_on_hand. None on a failed/degraded broker read."""
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            view = BrokerAccountViewEngine().snapshot()
            if not view.get("reads_ok", True):
                return None
            rows = view.get("positions", []) or []
            from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
            tb = TbillCashSweepEngine.symbol()

            def _is_tb(r):
                return ((str(r.get("symbol") or "").split() or [""])[0]).upper() == tb

            at_risk_mv = sum(float(r.get("current_price", 0) or 0) * float(r.get("quantity", 0) or 0)
                             for r in rows if not _is_tb(r))
            return round(equity - at_risk_mv, 2)
        except Exception:
            return None

    @classmethod
    def _live(cls):
        """(equity, deployable_cash) with a short TTL cache. Either may be None on a failed read.

        A failed equity read returns equity=None — it does NOT mask the failure with the static base.
        Masking it made the degraded branch in budget_usd() unreachable and silently sized every sleeve
        off $10k (skipping the cash clamp too). Returning None lets callers take their explicit
        fallback/degraded path, so a broker-read outage can't hand out full-base budgets as if real."""
        now = time()
        c = cls._cache
        if c["equity"] is not None and (now - c["t"]) < cls._CACHE_TTL_S:
            return c["equity"], c["cash"]
        equity = cls._read_equity()          # None when the real read failed — surfaced, not masked
        cash = cls._read_deployable_cash(equity) if equity is not None else None
        cls._cache = {"t": now, "equity": equity, "cash": cash}
        return equity, cash

    # ---- the number every sleeve asks for -------------------------------------------------------

    @classmethod
    def budget_usd(cls, sleeve, clamp_to_cash=True):
        """Dollar budget for a sleeve = pct_of_equity * live mission equity, clamped to live
        deployable cash (so no single sleeve over-commits the book). Falls back to the pre-conversion
        static dollar cap only if the equity read itself is unavailable — never returns a guess."""
        s = cls._canon(sleeve)
        equity, cash = cls._live()
        pct = cls.pct(s)
        # A failed equity read (_live returns None) is degraded — prefer the explicit per-sleeve
        # fallback dollar figure over sizing off a masked static base.
        if equity is None:
            return cls._FALLBACK_USD.get(s, 0.0)
        budget = (pct / 100.0) * equity
        if clamp_to_cash and cash is not None and cash >= 0:
            budget = min(budget, cash)
        return round(max(0.0, budget), 2)

    # A sleeve's own deployed value may reach this multiple of its budget before new buys are refused.
    # >1 gives headroom for whole-share rounding + intraday marks; the 2026-08-07 carry SVXY overshoot
    # (87 shares / $5.2k vs a ~$2.3k budget) is well beyond it, so it is caught while legit sizing isn't.
    SLEEVE_DEPLOY_CAP_FRAC = 1.15

    @classmethod
    def deployment_headroom_usd(cls, sleeve, sleeve_deployed_usd):
        """USD this sleeve may still BUY without exceeding its own budget x SLEEVE_DEPLOY_CAP_FRAC. <=0
        means the sleeve is at/over its budget -> refuse new buys (sells still allowed). The per-sleeve
        analog of the book cap: stops ONE sleeve eating the whole book within the total ceiling."""
        budget = cls.budget_usd(sleeve)
        if budget <= 0:
            return 0.0
        return max(0.0, budget * cls.SLEEVE_DEPLOY_CAP_FRAC - max(0.0, float(sleeve_deployed_usd or 0)))

    CONDOR_MAX_LOSS_PCT_DEFAULT = 5.0        # per-condor max loss as % of equity
    CONDOR_MAX_LOSS_FLOOR_USD = 500.0        # ...but never below this (strikes are quantized — below
    #                                          a floor, wide-strike names can't form a defined-risk condor)

    @classmethod
    def per_condor_max_loss(cls):
        """Per-CONDOR max-loss cap = max(pct-of-equity, floor). The % scales the cap up as the book
        grows (consistent with the sleeve portfolio caps); the floor stops a drawdown from shrinking it
        below the minimum size at which a condor is still tradeable — the exact 'too tight' problem that
        skipped the higher-priced earnings names at a fixed $300. Env: GREYLINE_CONDOR_MAX_LOSS_PCT /
        GREYLINE_CONDOR_MAX_LOSS_FLOOR_USD."""
        equity, _ = cls._live()
        eq = equity if equity else cls.DEFAULT_BASE_USD
        try:
            pct = float(getenv("GREYLINE_CONDOR_MAX_LOSS_PCT", "") or cls.CONDOR_MAX_LOSS_PCT_DEFAULT)
        except (TypeError, ValueError):
            pct = cls.CONDOR_MAX_LOSS_PCT_DEFAULT
        try:
            floor = float(getenv("GREYLINE_CONDOR_MAX_LOSS_FLOOR_USD", "") or cls.CONDOR_MAX_LOSS_FLOOR_USD)
        except (TypeError, ValueError):
            floor = cls.CONDOR_MAX_LOSS_FLOOR_USD
        return round(max((pct / 100.0) * eq, floor), 2)

    @classmethod
    def snapshot(cls):
        """Human/endpoint view of the live budget book."""
        equity, cash = cls._live()
        table = cls.pct_table()
        budgets = {s: cls.budget_usd(s) for s in table}
        degraded = equity is None   # equity read failed → budgets below are explicit fallbacks, not live
        try:
            risk_budget = cls.risk_budget_advisory()   # never let the advisory break the budget read
        except Exception as e:
            risk_budget = {"status": "RISK_BUDGET_UNAVAILABLE", "error": str(e)[:120]}
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mission_equity": equity,
            "deployable_cash": cash,
            "degraded": degraded,
            "risk_budget": risk_budget,
            "total_target_pct": cls.total_pct(),
            "targets_full_deployment": cls.total_pct() >= 99.5,   # False at the current 97% target
            "cash_buffer_pct": round(max(0.0, 100.0 - cls.total_pct()), 4),   # deliberate unallocated headroom
            "sleeves": {
                s: {"pct_of_equity": table[s], "budget_usd": budgets[s]}
                for s in table
            },
            "note": ("Budgets are %%-of-equity, clamped to live deployable cash. Sum of targets is "
                     "%.1f%% of equity — the remaining %.1f%% is deliberate unallocated headroom (not "
                     "fully deployed). Sleeves are further clamped to live deployable cash. Book-level "
                     "backstop is the daily-loss governor (-4%%/-7%%)."
                     % (cls.total_pct(), max(0.0, 100.0 - cls.total_pct()))),
            "status": "SLEEVE_BUDGET_DEGRADED" if degraded else "SLEEVE_BUDGET_OK",
        }
