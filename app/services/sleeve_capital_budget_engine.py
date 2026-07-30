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

Default percentages preserve the operator's existing RELATIVE balance (trend heaviest, earnings
lightest) but scale the SUM from 79% to 100% so the whole book is deployable. They are
env-overridable (GREYLINE_<SLEEVE>_ALLOC_PCT) — this engine only reads knobs, it never trades.

SAFETY POSTURE: 100%-deployable REMOVES the old "keep ~21% safe in T-bills" buffer. The remaining
book-level backstop is the daily-loss governor (warn -4% / halt -7%), which is MONITOR+ALERT, not
an auto-flatten. Deploying more concentrates the unproven-edge risk — a deliberate operator choice.
"""

from datetime import datetime
from os import getenv
from time import time


class SleeveCapitalBudgetEngine:

    # Default targets as PERCENT of live mission equity. The 5 core sleeves sum to 100 -> the whole
    # book is deployable. managed_futures is a tracked sleeve too but defaults to 0 (funded via
    # GREYLINE_MANAGED_FUTURES_ALLOC_PCT when armed); when it's funded, another sleeve is reduced to
    # keep the live sum <= 100 (2026-07-30: it REPLACED trend — trend set to 0% + disabled).
    DEFAULT_PCT = {
        "momentum": 25.0,
        "trend": 28.0,
        "vol_carry": 20.0,
        "vrp": 15.0,
        "earnings": 12.0,
        "managed_futures": 0.0,
    }
    # Aliases so callers can use either name for the carry sleeve.
    _ALIAS = {"carry": "vol_carry"}

    # Fallback dollar budgets if BOTH the env pct and the equity read are unavailable (never trade
    # on a mystery number). These mirror the pre-conversion static caps.
    _FALLBACK_USD = {
        "momentum": 2000.0, "trend": 2217.0, "vol_carry": 1583.0, "vrp": 1200.0, "earnings": 900.0,
    }
    DEFAULT_BASE_USD = 10000.0
    _CACHE_TTL_S = 5.0            # coalesce the equity/cash reads across sleeves within one cycle

    _cache = {"t": 0.0, "equity": None, "cash": None}

    # ---- knobs ---------------------------------------------------------------------------------

    @classmethod
    def _canon(cls, sleeve):
        s = (sleeve or "").strip().lower()
        return cls._ALIAS.get(s, s)

    @classmethod
    def pct(cls, sleeve):
        """Target percent-of-equity for a sleeve (env override GREYLINE_<SLEEVE>_ALLOC_PCT)."""
        s = cls._canon(sleeve)
        default = cls.DEFAULT_PCT.get(s, 0.0)
        raw = getenv("GREYLINE_%s_ALLOC_PCT" % s.upper(), "")
        try:
            v = float(raw) if str(raw).strip() else default
        except (TypeError, ValueError):
            v = default
        # sanity: a percent, not a fraction; clamp to [0, 100]
        return max(0.0, min(100.0, v))

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
        """(equity, deployable_cash) with a short TTL cache. Either may be None on a failed read."""
        now = time()
        c = cls._cache
        if c["equity"] is not None and (now - c["t"]) < cls._CACHE_TTL_S:
            return c["equity"], c["cash"]
        equity = cls._read_equity()
        if equity is None:
            equity = cls._base()          # last resort: the static book size, never a mystery number
        cash = cls._read_deployable_cash(equity)
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
        # If we couldn't read equity at all, _live() already substituted the static base; treat a
        # base-only equity as "degraded" and prefer the explicit per-sleeve fallback dollar figure.
        if equity is None:
            return cls._FALLBACK_USD.get(s, 0.0)
        budget = (pct / 100.0) * equity
        if clamp_to_cash and cash is not None and cash >= 0:
            budget = min(budget, cash)
        return round(max(0.0, budget), 2)

    @classmethod
    def snapshot(cls):
        """Human/endpoint view of the live budget book."""
        equity, cash = cls._live()
        table = cls.pct_table()
        budgets = {s: cls.budget_usd(s) for s in table}
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mission_equity": equity,
            "deployable_cash": cash,
            "total_target_pct": cls.total_pct(),
            "deployable_100pct": cls.total_pct() >= 99.5,   # can the sleeves collectively use ~all cash
            "sleeves": {
                s: {"pct_of_equity": table[s], "budget_usd": budgets[s]}
                for s in table
            },
            "note": ("Budgets are %%-of-equity, clamped to live deployable cash. Sum of targets is "
                     "%.1f%% of equity — the book can deploy up to ~100%% of cash when sleeves have "
                     "opportunities. Book-level backstop is the daily-loss governor (-4%%/-7%%)."
                     % cls.total_pct()),
            "status": "SLEEVE_BUDGET_OK",
        }
