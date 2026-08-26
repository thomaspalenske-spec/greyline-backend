"""Hypothetical position sizing for the zero-capital shadows (operator decision 2026-08-17).

The shadows commit NO capital and place NO orders, so they have no real position size. To make the
dashboard's P/L $ a concrete, comparable dollar figure, each open shadow position is treated as a fixed
number of 100-share lots ("contracts"), 1 by default. This is clearly hypothetical — it scales the
per-share move into dollars, it does not imply any capital was deployed.

  P/L $ (total) = per-share P/L  ×  SHARES_PER_CONTRACT  ×  contracts

One definition, imported by every shadow engine, so the sizing can't drift between cards.
"""

from os import getenv

SHARES_PER_CONTRACT = 100


def default_contracts():
    """Lots per open shadow position (1 = one 100-share lot). Override via GREYLINE_SHADOW_CONTRACTS."""
    try:
        n = int(getenv("GREYLINE_SHADOW_CONTRACTS", "1") or 1)
        return n if n >= 1 else 1
    except (TypeError, ValueError):
        return 1


def pnl_dollars(pnl_per_share, contracts=None):
    """Total hypothetical dollar P/L for a shadow position: per-share × 100 × contracts."""
    if pnl_per_share is None:
        return None
    c = default_contracts() if contracts is None else max(1, int(contracts))
    return round(float(pnl_per_share) * SHARES_PER_CONTRACT * c, 2)


# CME/CBOT/COMEX/NYMEX/CFE contract multipliers — USD change in ONE contract's value per 1.0 move in the
# quoted price the futures shadow stores (entry_close / live_last, straight off TS's continuous @ROOT series).
# This is the "per-contract point value" the futures shadow deferred (2026-08-17) rather than fabricate a wrong
# share-style dollar; wiring the verified table (2026-08-25) turns the card's "—" into a correct P/L $. The key
# is the shadow's root symbol (e.g. "ES"), the value already folds in the quote unit, so pnl = move × value.
# VERIFIED per exchange contract specs — a root NOT in this map keeps "—" (never a guessed dollar).
FUTURES_POINT_VALUES = {
    # CME equity index — USD index points
    "ES": 50.0,     # E-mini S&P 500   $50 × index
    "NQ": 20.0,     # E-mini Nasdaq-100 $20 × index
    "RTY": 50.0,    # E-mini Russell 2000 $50 × index
    "YM": 5.0,      # E-mini Dow        $5 × index
    # CBOT interest rates — decimalized points, $ per 1.0 point (2Y has $200k face → $2000/pt, rest $100k → $1000/pt)
    "US": 1000.0,   # 30Y T-Bond (ZB)
    "TY": 1000.0,   # 10Y T-Note (ZN)
    "FV": 1000.0,   # 5Y T-Note (ZF)
    "TU": 2000.0,   # 2Y T-Note (ZT)
    # NYMEX energy — $/unit × contract size
    "CL": 1000.0,   # Crude    1,000 bbl × $/bbl
    "NG": 10000.0,  # Nat Gas  10,000 MMBtu × $/MMBtu
    "RB": 42000.0,  # RBOB     42,000 gal × $/gal
    # COMEX/NYMEX metals — $/oz or $/lb × contract size
    "GC": 100.0,    # Gold     100 oz × $/oz
    "SI": 5000.0,   # Silver   5,000 oz × $/oz
    "HG": 25000.0,  # Copper   25,000 lb × $/lb
    "PL": 50.0,     # Platinum 50 oz × $/oz
    # CBOT grains — 5,000 bu, quoted in CENTS/bu → $50 per 1.0 cent
    "C": 50.0,      # Corn
    "S": 50.0,      # Soybeans
    "W": 50.0,      # Wheat
    # CFE volatility
    "VX": 1000.0,   # VIX future $1,000 × index
}


def futures_point_value(symbol):
    """Verified USD-per-point contract multiplier for a futures ROOT, or None if not in the table (→ keep "—")."""
    return FUTURES_POINT_VALUES.get(str(symbol or "").upper().lstrip("@"))


def _fx_quote_to_usd(symbol, live_last):
    """Factor converting a per-unit price move in the pair's QUOTE currency into USD.

    The per-unit move (live_last - entry_close) of an FX pair is denominated in the QUOTE currency, not USD:
      - '...USD' pairs (EURUSD, GBPUSD, AUDUSD): quote already IS USD                 -> 1.0
      - 'USD...' pairs (USDJPY, USDCAD, USDCHF): quote is foreign, divide by live rate -> 1/live_last
    Without this, a JPY-quoted move (e.g. 0.539 JPY) is multiplied by 100 and mislabeled dollars ($53.90 for a
    move truly worth ~$0.34). A non-USD cross falls through to 1.0 (not in the current FX universe)."""
    s = str(symbol or "").upper().replace("/", "")
    if len(s) == 6 and live_last and float(live_last) > 0:
        if s.endswith("USD"):
            return 1.0
        if s.startswith("USD"):
            return 1.0 / float(live_last)
    return 1.0


def enrich_open_rows(rows, contracts=None, fx=False, dollars=True, futures=False):
    """Add contracts + per-share + total-dollar P/L to each per-position shadow row IN PLACE, from its
    entry_close / live_last / side. Used by the cohort shadows (momentum, ETF, vol-ETP, futures, FX) whose
    rows share that shape, so every card sizes P/L the same way. Rows missing a live mark keep None.

    fx=True marks the rows as spot-FX pairs: the per-unit move is in the pair's QUOTE currency, so the dollar
    P/L is converted to USD (see _fx_quote_to_usd). Equity/ETF rows (fx=False) are already USD-denominated.

    dollars=False marks rows whose per-unit move does NOT convert to a fixed USD figure without external
    plumbing — the futures shadow: each contract has its own point value (ES $50/pt, ZB $1000/pt, grains
    quoted in cents) and the continuous @ROOT series can carry roll gaps, so a share-style (move x 100) dollar
    is meaningless. Those rows get the contract count + raw per-unit move for context but NO fabricated
    pnl_dollars (a `pnl_dollars_na` reason is attached instead); the % return is the measurement, matching the
    engine's point-value plumbing that is deferred until arm."""
    c = default_contracts() if contracts is None else max(1, int(contracts))
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        r.setdefault("contracts", c)
        side = str(r.get("side") or "").upper()
        try:
            ec, ll = float(r.get("entry_close")), float(r.get("live_last"))
        except (TypeError, ValueError):
            continue
        if ec <= 0 or ll <= 0:
            continue
        pps = (ll - ec) if side in ("BUY", "LONG") else (ec - ll)   # signed by side, like unrealized_pct
        r["pnl_per_share"] = round(pps, 4)
        if futures:
            # UNREALIZED dollar P/L on ONE open futures contract = price move × the verified contract multiplier
            # (NOT the share-style ×100). A root without a verified point value keeps "—" rather than a guess.
            pv = futures_point_value(r.get("symbol"))
            if pv is None:
                r["pnl_dollars_na"] = "no verified point value for %s; %% return is the measure" % r.get("symbol")
                continue
            r["point_value"] = pv
            r["pnl_dollars"] = round(pps * pv * c, 2)
            continue
        if not dollars:
            r["pnl_dollars_na"] = "per-contract point value deferred until arm; % return is the measure"
            continue
        usd = _fx_quote_to_usd(r.get("symbol"), ll) if fx else 1.0
        r["pnl_dollars"] = pnl_dollars(pps * usd, c)
    return rows
