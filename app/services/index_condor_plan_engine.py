"""Index (XSP-first) defined-risk condor PLANNER — feeds the condor shadow, never books.

Recommendation follow-through (2026-08-10): the deepest, most-persistent variance-risk premium lives in
INDEX options, and their spreads are the tightest anywhere — the exact cost constraint that killed the
single-name condor sleeves. XSP (mini-SPX, 1/10th SPX) is right-sized for the $10k book AND cash-settled
(European, no assignment/pin) so it sidesteps the SIM atomic-condor-close break that RETIRED the VRP /
earnings sleeves.

This engine builds ONE defined-risk iron condor per index name off the SAME UW chain path the sleeves use
(`UWOptionChainEngine.get_chain_snapshot` -> `ConditionalVRPShortPremiumEngine.build_condor`), producing the
identical condor dict the condor shadow already consumes. It is MEASUREMENT-ONLY: the condor shadow records
what this WOULD open (tagged sleeve 'index_vrp') and marks it to UW mid — NO orders, NO budget, no live
sleeve. Gated OFF by default (GREYLINE_INDEX_CONDOR_SHADOW). XSP first; SPX/NDX/RUT are a trivial follow-on
(UW serves all of them via the same /api/stock/{root} path — verified 2026-08-10).
"""

from os import getenv


class IndexCondorPlanEngine:

    # Per-name (strike_grid, max_loss_cap). Each index/ETF trades a different strike ladder and price, so
    # the wing grid + $10k-right-sized cap are calibrated per name (all yield ~qty 1). XSP is cash-settled
    # (European, no assignment); QQQ/IWM are American-style ETF options — identical for a UW-mid mark, but
    # the ETFs carry short-leg early-assignment risk IF ever traded live (a cash-settled mini would be the
    # live upgrade). Grouped under one 'index_vrp' verdict; each condor keeps its symbol for per-index split.
    # Per-name (strike_grid, max_loss_cap, sleeve). The SLEEVE tag is how the condor shadow's by_sleeve
    # verdict separates the risk factors — the equity indices pool as index_vrp, but GOLD is measured on its
    # OWN (commodity_vrp) because the whole reason to add it is the DECORRELATION test: pooling gold with
    # equities would blend the exact two things we're comparing (is VRP universal, or just equity beta?).
    NAME_CONFIG = {
        "XSP": {"grid": 10, "cap": 1000.0, "sleeve": "index_vrp"},   # S&P 500 (mini-SPX, cash-settled)
        "QQQ": {"grid": 5,  "cap": 500.0,  "sleeve": "index_vrp"},   # Nasdaq-100 (ETF)
        "IWM": {"grid": 5,  "cap": 500.0,  "sleeve": "index_vrp"},   # Russell 2000 (ETF) — richest equity VRP
        "GLD": {"grid": 5,  "cap": 500.0,  "sleeve": "commodity_vrp"},  # GOLD — DECORRELATED from equity vol
        "USO": {"grid": 5,  "cap": 500.0,  "sleeve": "energy_vrp"},     # OIL — new decorrelated factor, but
        #   FAT-TAILED (OPEC/geopolitical/supply jumps): the shadow measures whether the rich energy VRP
        #   survives its tail net of cost. Most interesting to MEASURE, most dangerous to ever ARM.
        "TLT": {"grid": 3,  "cap": 300.0,  "sleeve": "rates_vrp"},      # 20Y TREASURY — rates vol, another
        #   decorrelated factor (often NEGATIVELY corr to equity in risk-off). Low price (~$89) + low vol +
        #   sparse strikes -> finer $3 grid + smaller cap to stay qty 1 (condors are narrow in % terms).
        "IBIT": {"grid": 2, "cap": 300.0,  "sleeve": "crypto_vrp"},     # BITCOIN — richest VRP of all, but
        #   the MOST EXTREME tail of any asset (20-30% days, weekend gaps, 50%+ drawdowns). Deliberately the
        #   SMALLEST cap ($300 -> ~$154 max loss) to bound per-position tail damage. Ultimate measure/never-arm.
    }
    NAMES = list(NAME_CONFIG)       # SPX/NDX too big for $10k; XND/MRUT cash-settled minis available (UW-probed)
    TARGET_DTE = 42
    DTE_BAND = (28, 56)

    # CONDITIONAL harvest: only sell premium when IV is RICH (trailing rank >= top tercile) — GreyLine's own
    # research found the VRP is ~9.6x conditional on rich IV. Reuses the PROVEN gate the retired VRP sleeve
    # used (ConditionalVRPForwardPanelEngine.rich_iv_candidates). XSP has NO UW IV series (cash-settled index)
    # so its richness is read off SPY (identical S&P 500 implied vol). Fail-CLOSED: no confirmed richness -> no
    # condor (never sell un-conditioned premium mislabeled as conditional).
    IV_PROXY = {"XSP": "SPY"}       # name -> the ticker whose UW IV-rank stands in for it (default: itself)

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_INDEX_CONDOR_SHADOW", "false") or "false").strip().lower() == "true"

    @staticmethod
    def _conditional():
        # default ON — the whole point of this change is to harvest ONLY rich IV. Set false to open
        # unconditionally (the pre-2026-08-10 behaviour), e.g. to A/B the conditional lift.
        return (getenv("GREYLINE_CONDOR_CONDITIONAL", "true") or "true").strip().lower() == "true"

    def _rich_iv(self):
        """{proxy_ticker: iv_rank} for the index names' IV proxies that pass the rich-IV gate today. Empty
        on any screen failure -> fail-closed (nothing opens). Reuses the proven conditional-VRP panel."""
        try:
            from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine
            proxies = sorted({self.IV_PROXY.get(n, n) for n in self.NAMES})
            return {c["ticker"]: c["iv_rank"] for c in ConditionalVRPForwardPanelEngine().rich_iv_candidates(proxies)}
        except Exception:
            return {}

    @staticmethod
    def _max_loss_cap():
        # XSP right-sizing for the $10k book (~one 10-wide condor ≈ $800-900). Own knob so it never rides
        # the single-name cap. Default 1000 -> qty 1 at a 10-point width.
        try:
            return float(getenv("GREYLINE_INDEX_CONDOR_MAX_LOSS", "1000"))
        except (TypeError, ValueError):
            return 1000.0

    @staticmethod
    def _strike_grid():
        # Index options list $1 strikes; the single-name build_condor picks the NARROWEST fitting wing, so on
        # a $1 grid it builds a $1-wide condor whose ~$0.30 credit can't clear the 4-leg round-trip cost.
        # Coarsen to a normal index wing width (10 pts) — exactly how XSP condors actually trade — so the
        # wing has meaningful credit. Behaviour-preserving for coarse-strike names (they're already on it).
        try:
            return int(getenv("GREYLINE_INDEX_CONDOR_STRIKE_GRID", "10"))
        except (TypeError, ValueError):
            return 10

    @staticmethod
    def _coarsen(contracts, builder, grid):
        """Keep only strikes on the `grid` (e.g. every 10 pts) so build_condor's wing selection yields a
        tradeable width on a fine index strike ladder. Fails open: a parse miss keeps the contract."""
        if grid <= 1:
            return contracts
        out = []
        for c in contracts:
            try:
                k = (builder._leg(c) or {}).get("strike")
                if k is None or round(float(k)) % grid == 0:
                    out.append(c)
            except Exception:
                out.append(c)
        return out

    def plan(self):
        """Build one defined-risk condor per index name (or a skip reason each). MEASUREMENT-ONLY — returns
        {'planned': [condor,...], 'errors': {name: reason}, 'expiry': iso}. Never books, never sizes a real
        order. A name that throws is recorded in `errors` (never silently dropped — that would bias the
        forward-test toward the days it happened to work), mirroring the condor shadow's own discipline."""
        from app.services.uw_option_chain_engine import UWOptionChainEngine
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine

        expiry = UWOptionChainEngine.monthly_expiry(target_dte=self.TARGET_DTE, band=self.DTE_BAND)
        chain = UWOptionChainEngine()
        builder = ConditionalVRPShortPremiumEngine()
        conditional = self._conditional()
        rich = self._rich_iv() if conditional else {}   # {proxy: iv_rank} passing the top-tercile gate
        planned, errors, skipped = [], {}, {}
        for name in self.NAMES:
            cfg = self.NAME_CONFIG.get(name, {})
            grid = int(cfg.get("grid") or self._strike_grid())
            cap = float(cfg.get("cap") or self._max_loss_cap())
            proxy = self.IV_PROXY.get(name, name)
            # CONDITIONAL GATE: only harvest when IV is rich (the ~9.6x lever). Fail-closed — no confirmed
            # richness -> skip (never sell un-conditioned premium). Skips are a legitimate "no trade today",
            # kept separate from errors so a quiet-vol day doesn't read as a broken sleeve.
            if conditional and proxy not in rich:
                skipped[name] = f"IV not rich — {proxy} below top-tercile (no harvest; conditional VRP gate)"
                continue
            try:
                snap = chain.get_chain_snapshot(name, expiry)
                contracts = self._coarsen(snap.get("contracts") or [], builder, grid)
                if not contracts:
                    errors[name] = snap.get("status") or "no contracts"
                    continue
                con = builder.build_condor(name, contracts, max_loss_cap=cap)
                if con.get("skip"):
                    errors[name] = con["skip"]
                    continue
                con["expiration"] = expiry
                # RECORD the entry IV-rank that IS the edge (VRP ~9.6x conditional on rich IV) — the shadow
                # stores it so a closed condor's realized P&L can be read against the richness it was sold into.
                con["iv_rank"] = rich.get(proxy) if conditional else None
                con["iv_proxy"] = proxy if proxy != name else None
                con["_sleeve"] = cfg.get("sleeve") or "index_vrp"   # per-factor tag (index_vrp / commodity_vrp)
                planned.append(con)
            except Exception as e:
                errors[name] = repr(e)[:160]
        return {"planned": planned, "errors": errors, "skipped": skipped, "expiry": expiry,
                "names": list(self.NAMES), "config": self.NAME_CONFIG,
                "conditional": conditional, "rich_iv": rich,
                "status": "INDEX_CONDOR_PLAN_READY" if planned else "INDEX_CONDOR_PLAN_EMPTY"}

    def status(self):
        return {"enabled": self.enabled(), "conditional": self._conditional(),
                "names": list(self.NAMES), "config": self.NAME_CONFIG,
                "iv_proxy": self.IV_PROXY, "target_dte": self.TARGET_DTE,
                "rich_iv_now": self._rich_iv() if self._conditional() else "unconditional",
                "note": ("MEASUREMENT-ONLY condor planner across 5 decorrelated factors (index/commodity/"
                         "energy/rates/crypto VRP), NO orders/budget. CONDITIONAL harvest: opens only when IV "
                         "is rich (top-tercile trailing rank — the ~9.6x VRP lever), fail-closed; entry IV-rank "
                         "recorded per condor. XSP richness proxied off SPY (no UW IV series for the index).")}
