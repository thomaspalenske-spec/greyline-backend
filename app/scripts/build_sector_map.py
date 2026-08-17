"""Generate app/data/sector_map.json for the whole tradable universe.

PortfolioExposureEngine._sector() carried a hand-written dict covering the old 98-name
universe. Expanding to the S&P 500 left 9 of the first 10 selected names unmapped, and
unmapped is not a harmless default: everything unclassified pools into a single "UNKNOWN"
bucket, so ten correlated semiconductor names read as one undifferentiated blob and the
concentration limit stays silent. The engine's own comment warned that "the next universe
addition" would do this quietly. It did.

Concretely, on 2026-07-19 the strategy's top 10 was SNDK, WDC, CIEN, MRVL, STX, MU, GLW,
INTC, COHR, TER — memory, storage, semis and optical, effectively one bet. All ten are
Technology, which at $750/name is 75% of capital and breaches the 70% sector cap. Unmapped,
they measured 67.5% in the UNKNOWN bucket and passed.

Sectors come from Unusual Whales (already paid for): the stock screener returns them in
bulk, and the company profile endpoint covers stragglers one at a time.

Usage:  PYTHONPATH=. python app/scripts/build_sector_map.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

OUT = Path("app/data/sector_map.json")

# UW's vocabulary -> the vocabulary PortfolioExposureEngine already speaks, so the limit,
# the dashboards and the existing hand-written entries all keep agreeing.
# Keyed on the UPPERCASED, underscored form, because the two UW endpoints disagree on
# case: the screener says "Consumer Cyclical" and the profile says "CONSUMER_CYCLICAL".
# Matching only one of them silently splits a sector into two buckets, which is worse
# than no mapping — a 10-name cluster would read as two comfortable 5-name ones and the
# concentration limit would stay quiet for the wrong reason.
NORMALISE = {
    "TECHNOLOGY": "TECHNOLOGY",
    "FINANCIAL_SERVICES": "FINANCIALS",
    "FINANCIALS": "FINANCIALS",
    "HEALTHCARE": "HEALTHCARE",
    "CONSUMER_CYCLICAL": "CONSUMER_DISCRETIONARY",
    "CONSUMER_DISCRETIONARY": "CONSUMER_DISCRETIONARY",
    "CONSUMER_DEFENSIVE": "CONSUMER_STAPLES",
    "CONSUMER_STAPLES": "CONSUMER_STAPLES",
    "UTILITIES": "UTILITIES",
    "REAL_ESTATE": "REAL_ESTATE",
    "COMMUNICATION_SERVICES": "COMMUNICATIONS",
    "COMMUNICATIONS": "COMMUNICATIONS",
    "ENERGY": "ENERGY",
    "BASIC_MATERIALS": "MATERIALS",
    "MATERIALS": "MATERIALS",
    "INDUSTRIALS": "INDUSTRIALS",
}


def normalise(value):
    if not value:
        return None
    key = str(value).strip().upper().replace(" ", "_")
    return NORMALISE.get(key, key)


def main():
    from dotenv import load_dotenv
    load_dotenv(".env")
    from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
    from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine

    provider = UnusualWhalesProvider()
    # The FULL traded universe, not just momentum: options/VRP names and the ETF sleeves can all be
    # HELD, so each needs a sector or it is invisible to the concentration cap. (The historical CSV dir
    # is the full-market PIT archive — thousands of names we never trade — so it is NOT the universe.)
    symbols = set(MomentumReversalStrategyEngine()._symbols())
    try:
        from app.services.vrp_research_engine import VRPResearchEngine
        symbols |= set(VRPResearchEngine.CURATED_FALLBACK)
        from app.services.optionable_universe_engine import OptionableUniverseEngine
        symbols |= set(OptionableUniverseEngine().names() or [])
        from app.services.trend_following_engine import TrendFollowingEngine
        from app.services.managed_futures_engine import ManagedFuturesEngine
        symbols |= set(TrendFollowingEngine.BASKET) | set(ManagedFuturesEngine.BASKET)
        symbols |= {"SGOV", "SVXY", "QQQM", "GLDM"}
    except Exception as exc:
        print("traded-universe union warning:", exc)
    symbols = sorted(symbols)

    # Bulk first: one screener call covers ~500 of the S&P 500.
    resp = provider._get("/api/screener/stocks", params={"is_s_p_500": "true", "limit": 500})
    rows = (resp.get("data") if isinstance(resp, dict) else resp) or []
    mapping = {}
    for row in rows:
        sector = normalise(row.get("sector"))
        if row.get("ticker") and sector:
            mapping[row["ticker"]] = sector
    print(f"screener mapped {len(mapping)}")

    # Then the stragglers (ETFs, non-index names) one profile call each.
    missing = [s for s in symbols if s not in mapping]
    print(f"resolving {len(missing)} individually...")
    unresolved = []
    for sym in missing:
        try:
            prof = provider._get(f"/api/companies/{sym}/profile")
            data = (prof.get("data") if isinstance(prof, dict) else prof) or {}
            if isinstance(data, list):
                data = data[0] if data else {}
            sector = normalise(data.get("sector"))
            if sector:
                mapping[sym] = sector
            else:
                unresolved.append(sym)
        except Exception:
            unresolved.append(sym)
        time.sleep(0.15)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.utcnow().isoformat(),
        "symbols": len(mapping),
        "unresolved": sorted(unresolved),
        "sectors": mapping,
    }, indent=2, sort_keys=True))

    from collections import Counter
    print(json.dumps({"mapped": len(mapping), "unresolved": len(unresolved),
                      "universe": len(symbols),
                      "by_sector": dict(Counter(mapping.values()).most_common())}, indent=2))
    if unresolved:
        # Never silent: an unresolved symbol is a hole in the concentration limit.
        print("UNRESOLVED (these stay UNKNOWN and are invisible to the sector cap):")
        print("  " + ", ".join(sorted(unresolved)))


if __name__ == "__main__":
    main()
