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


def enrich_open_rows(rows, contracts=None):
    """Add contracts + per-share + total-dollar P/L to each per-position shadow row IN PLACE, from its
    entry_close / live_last / side. Used by the cohort shadows (momentum, ETF, vol-ETP, futures, FX) whose
    rows share that shape, so every card sizes P/L the same way. Rows missing a live mark keep None."""
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
        r["pnl_dollars"] = pnl_dollars(pps, c)
    return rows
