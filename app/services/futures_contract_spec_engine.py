"""Contract specifications for futures — the piece that makes futures sizing coherent.

RESEARCH / STAGING. This is NOT wired to live execution and must not be until the futures
sizing, margin, roll and exposure model around it is built and validated. A futures
position sized like an equity would be catastrophically wrong: a single /ES contract is
$50 x the index (~$300k notional), not one $6,000 "share", so an equity-style $750 slice
would either buy nothing or, if forced, hold ~50x the intended risk.

Why the equity pipeline cannot absorb futures as-is:
  * MULTIPLIER — P&L per point is a contract multiplier, not 1. /ES=$50, /CL=$1,000,
    /GC=$100. Every P&L, exposure and stop-distance calc downstream assumes multiplier 1.
  * MARGIN, not cash — a contract is controlled on margin (a few % of notional), so cash
    accounting and the "$500 = 5% of $10k" position cap are meaningless.
  * ROLL — a continuous series (@ES) splices expiring contracts; backtesting on it without
    roll adjustment injects artificial gaps at each roll.
  * INDIVISIBLE — you hold whole contracts. At $10k, ONE /ES contract is 30x the account.
    Micro futures (/MES=$5, /MCL=$100) exist precisely for small accounts and are the only
    futures a $10k book could hold at all.

This module encodes the specs so that sizing CAN be made coherent later, and so the
research backtests can price futures P&L correctly. It computes required capital and
rejects contracts an account cannot afford — the honest gate that keeps a $10k book from
pretending it can trade /ES.
"""


class FuturesContractSpecEngine:

    # symbol -> (name, point_multiplier_usd, approx_initial_margin_usd, tradestation_symbol)
    # Margins are approximate and move with volatility; treated as a floor for affordability,
    # never as an exact broker figure.
    SPECS = {
        # E-mini index futures (full size — far too large for a $10k book)
        "ES":  ("E-mini S&P 500",        50.0,  13000, "@ES"),
        "NQ":  ("E-mini Nasdaq-100",     20.0,  18000, "@NQ"),
        "YM":  ("E-mini Dow",             5.0,   9000, "@YM"),
        "RTY": ("E-mini Russell 2000",   50.0,   8000, "@RTY"),
        # MICRO index futures — the only index futures a small account can hold
        "MES": ("Micro E-mini S&P 500",   5.0,   1300, "@MES"),
        "MNQ": ("Micro E-mini Nasdaq",    2.0,   1800, "@MNQ"),
        "MYM": ("Micro E-mini Dow",       0.5,    900, "@MYM"),
        "M2K": ("Micro E-mini Russell",   5.0,    800, "@M2K"),
        # Energy
        "CL":  ("Crude Oil",           1000.0,   6000, "@CL"),
        "MCL": ("Micro Crude Oil",      100.0,    600, "@MCL"),
        "NG":  ("Natural Gas",        10000.0,   4000, "@NG"),
        # Metals
        "GC":  ("Gold",                 100.0,  11000, "@GC"),
        "MGC": ("Micro Gold",            10.0,   1100, "@MGC"),
        "SI":  ("Silver",              5000.0,  14000, "@SI"),
        "SIL": ("Micro Silver",        1000.0,   2800, "@SIL"),
        "HG":  ("Copper",             25000.0,   6500, "@HG"),
        # Agriculture
        "ZC":  ("Corn",                  50.0,   2000, "@ZC"),
        "ZW":  ("Wheat",                 50.0,   2500, "@ZW"),
        "ZS":  ("Soybeans",              50.0,   3000, "@ZS"),
        # Rates
        "ZB":  ("30Y T-Bond",          1000.0,   4500, "@ZB"),
        "ZN":  ("10Y T-Note",          1000.0,   2000, "@ZN"),
    }

    def spec(self, symbol):
        return self.SPECS.get(str(symbol).upper().lstrip("@"))

    def is_futures(self, symbol):
        return str(symbol).upper().lstrip("@") in self.SPECS

    def contract_notional(self, symbol, price):
        """Full notional a contract controls = price x multiplier. NOT what you pay."""
        s = self.spec(symbol)
        if not s or price is None:
            return None
        try:
            return round(float(price) * s[1], 2)
        except (TypeError, ValueError):
            return None

    def point_pnl(self, symbol, points):
        """Dollar P&L for a move of `points`, one contract."""
        s = self.spec(symbol)
        if not s:
            return None
        try:
            return round(float(points) * s[1], 2)
        except (TypeError, ValueError):
            return None

    def affordable(self, symbol, capital, max_margin_fraction=0.5):
        """Whether ONE contract's initial margin fits within `max_margin_fraction` of
        capital. This is the gate that stops a $10k book from 'trading' /ES: it returns
        the verdict and the numbers, so a caller can reject rather than silently oversize.
        """
        s = self.spec(symbol)
        if not s:
            return {"symbol": symbol, "is_futures": False,
                    "status": "NOT_A_FUTURES_CONTRACT"}
        margin = s[2]
        ceiling = float(capital) * float(max_margin_fraction)
        ok = margin <= ceiling
        return {
            "symbol": symbol, "is_futures": True, "name": s[0],
            "multiplier": s[1], "approx_initial_margin": margin,
            "capital": float(capital), "margin_ceiling": round(ceiling, 2),
            "affordable": ok,
            "status": "FUTURES_AFFORDABLE" if ok else "FUTURES_MARGIN_EXCEEDS_ACCOUNT",
            "note": (None if ok else
                     f"one {symbol} contract needs ~${margin:,} margin, above the "
                     f"${ceiling:,.0f} ceiling ({max_margin_fraction:.0%} of ${capital:,.0f}); "
                     "use the micro contract if one exists"),
        }

    def affordable_futures(self, capital, max_margin_fraction=0.5):
        """Which futures a given account could actually hold one contract of."""
        return sorted(s for s in self.SPECS
                      if self.affordable(s, capital, max_margin_fraction)["affordable"])
