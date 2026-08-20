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


def enrich_open_rows(rows, contracts=None, fx=False):
    """Add contracts + per-share + total-dollar P/L to each per-position shadow row IN PLACE, from its
    entry_close / live_last / side. Used by the cohort shadows (momentum, ETF, vol-ETP, futures, FX) whose
    rows share that shape, so every card sizes P/L the same way. Rows missing a live mark keep None.

    fx=True marks the rows as spot-FX pairs: the per-unit move is in the pair's QUOTE currency, so the dollar
    P/L is converted to USD (see _fx_quote_to_usd). Equity/ETF rows (fx=False) are already USD-denominated."""
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
        usd = _fx_quote_to_usd(r.get("symbol"), ll) if fx else 1.0
        r["pnl_dollars"] = pnl_dollars(pps * usd, c)
    return rows
