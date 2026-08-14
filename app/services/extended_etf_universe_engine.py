"""Extended ETF universe — the 52 liquid ETFs the 2026-08-12 UW/TS scan found that were in NO existing
GreyLine basket. This is the canonical registry that ADDS them to GreyLine's universe.

WHAT "add to the universe" means here (and what it deliberately does NOT):
  * ADDS them as TRACKED, TAGGED CANDIDATE instruments — live-tracked by the quote stream and available as
    a candidate pool for sleeves/shadows to draw from. They become known, first-class instruments.
  * Does NOT arm any sleeve or deploy one dollar. An ETF earns its way into a LIVE sleeve only by clearing
    that sleeve's edge court (day-clustered, cost-net) — the same bar as everything else. A bigger universe
    is more CANDIDATES, not more edge, and after the over-deployment incident nothing auto-arms.

Each entry: subclass (what kind of fund) + fits (which existing sleeve it could extend) + caution (True for
the 2x leveraged / single-stock decay products — kept in the registry for completeness but never for a sleeve).
"""


class ExtendedEtfUniverseEngine:

    # ticker -> (subclass, fits_sleeves, caution)
    UNIVERSE = {
        # momentum / factor -> momentum, xs_momentum
        "MTUM": ("momentum_factor", "momentum,xs_momentum", False),
        "SPMO": ("momentum_factor", "momentum", False),
        "MAGS": ("thematic_growth", "momentum", False),
        "MGK":  ("growth", "momentum", False),
        "VOOG": ("growth", "momentum", False),
        "SCHG": ("growth", "momentum", False),
        "SCHD": ("dividend_quality", "low_vol", False),
        "DGRO": ("dividend_quality", "low_vol", False),
        "DVY":  ("dividend_quality", "low_vol", False),
        "HDV":  ("dividend_quality", "low_vol", False),
        "EFV":  ("intl_value", "xs_momentum", False),
        # options income -> potential new income sleeve
        "JEPI": ("options_income", "income", False),
        "JEPQ": ("options_income", "income", False),
        "QYLD": ("options_income", "income", False),
        # rates / credit -> trend, managed_futures
        "IEI":  ("rates", "trend,managed_futures", False),
        "MUB":  ("muni", "rates_carry", False),
        "VCIT": ("corp_credit", "credit", False),
        "EMB":  ("em_bond", "managed_futures", False),
        "PFF":  ("preferred", "credit,income", False),
        "BKLN": ("floating_credit", "credit", False),
        # commodity -> trend, managed_futures
        "IAU":  ("gold", "trend,managed_futures", False),
        "SGOL": ("gold", "managed_futures", False),
        "GDXJ": ("commodity_equity", "momentum", False),
        "WEAT": ("agriculture", "managed_futures", False),
        "PDBC": ("broad_commodity", "managed_futures", False),
        "REMX": ("strategic_metals", "thematic", False),
        "AMLP": ("energy_income", "income", False),
        # international / broad -> managed_futures, xs_momentum, trend
        "INDA": ("intl_single_country", "managed_futures,xs_momentum", False),
        "EWT":  ("intl_single_country", "managed_futures,xs_momentum", False),
        "MCHI": ("intl_single_country", "managed_futures,xs_momentum", False),
        "VGK":  ("intl_region", "managed_futures,xs_momentum", False),
        "VT":   ("global_broad", "diversifier", False),
        "ACWI": ("global_broad", "diversifier", False),
        "IWV":  ("us_broad", "diversifier", False),
        # international large-cap ADRs (Tier 3, 2026-08-14) -> single-name momentum/xs breadth. TRACKED ONLY:
        # single-name LIVE selection stays gated on re-opening the single-name VRP/optionable plumbing (the
        # ADRs' own tier note) — registering them here makes them candidates the court can measure, not armed.
        "SHEL": ("intl_adr", "momentum,xs_momentum", False),
        "NVO":  ("intl_adr", "momentum,xs_momentum", False),
        "TEVA": ("intl_adr", "momentum,xs_momentum", False),
        "VOD":  ("intl_adr", "momentum,xs_momentum", False),
        "JD":   ("intl_adr", "momentum,xs_momentum", False),
        # thematic / industry -> momentum, sector
        "JETS": ("thematic_industry", "momentum", False),
        "IYR":  ("sector_reit", "sector", False),
        "ITB":  ("sector", "sector", False),
        "IHI":  ("sector", "sector", False),
        "BOTZ": ("thematic_industry", "momentum", False),
        "AIQ":  ("thematic_industry", "momentum", False),
        "CIBR": ("thematic_industry", "momentum", False),
        "ICLN": ("thematic_industry", "momentum", False),
        "ITA":  ("sector", "sector", False),
        "IYW":  ("sector", "sector", False),
        "KBWB": ("sector", "sector", False),
        "ARKG": ("thematic_industry", "momentum", False),
        # crypto -> crypto VRP (IBIT proxy already exists)
        "FBTC": ("crypto", "crypto", False),
        "GBTC": ("crypto", "crypto", False),
        # leveraged / single-stock 2x — REGISTERED but CAUTION: never for a sleeve (decay products)
        "BITX": ("leveraged_crypto", "", True),
        "MSTU": ("leveraged_single_stock", "", True),
        "MUU":  ("leveraged_single_stock", "", True),
        "MULL": ("leveraged_single_stock", "", True),
    }

    @classmethod
    def all(cls):
        return [{"ticker": t, "subclass": s, "fits": f, "caution": c}
                for t, (s, f, c) in cls.UNIVERSE.items()]

    @classmethod
    def symbols(cls, include_caution=True):
        """The tickers, for tracking/candidate use. include_caution=False drops the 2x leveraged products."""
        return [t for t, (s, f, c) in cls.UNIVERSE.items() if include_caution or not c]

    @classmethod
    def for_sleeve(cls, sleeve):
        """Candidate tickers whose `fits` names this sleeve (excludes caution products). A sleeve can draw
        from this to propose new members — but each still passes the edge court before it trades."""
        s = str(sleeve).lower()
        return [t for t, (sub, fits, c) in cls.UNIVERSE.items()
                if not c and s in [x.strip() for x in fits.split(",") if x.strip()]]

    @classmethod
    def by_subclass(cls):
        out = {}
        for t, (s, f, c) in cls.UNIVERSE.items():
            out.setdefault(s, []).append(t)
        return {k: sorted(v) for k, v in sorted(out.items())}

    @classmethod
    def snapshot(cls):
        cautions = cls.symbols(include_caution=True)
        return {
            "count": len(cls.UNIVERSE),
            "tradeable_count": len(cls.symbols(include_caution=False)),
            "caution_count": sum(1 for _, (_, _, c) in cls.UNIVERSE.items() if c),
            "by_subclass": cls.by_subclass(),
            "instruments": cls.all(),
            "note": ("TRACKED CANDIDATES only — registered + live-tracked, NOT armed to any sleeve. Each earns "
                     "its way into a live sleeve via the edge court (day-clustered, cost-net). Caution=2x "
                     "leveraged/single-stock decay products: kept for completeness, never for a sleeve."),
            "status": "EXTENDED_ETF_UNIVERSE",
        }
