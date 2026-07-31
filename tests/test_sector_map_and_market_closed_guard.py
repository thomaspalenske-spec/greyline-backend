import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.portfolio_exposure_engine import PortfolioExposureEngine

UNIVERSE = Path("app/services/market_universe_engine.py")


# ---- sector map ----
# Unmapped symbols all pooled into one meaningless "UNKNOWN" bucket, so correlated names
# stacked up while the concentration limit read them as diversified. IBIT/COIN/ETHE/MSTR
# are one crypto bet, not four sectors.

def test_crypto_names_share_one_sector():
    e = PortfolioExposureEngine()
    sectors = {e._sector(s) for s in ("IBIT", "COIN", "ETHE", "MSTR")}
    assert sectors == {"CRYPTO"}


def test_index_futures_share_the_bucket_of_the_etf_they_track():
    e = PortfolioExposureEngine()
    assert e._sector("ES") == e._sector("SPY")
    assert e._sector("NQ") == e._sector("QQQ")


def test_full_traded_universe_is_mapped():
    # Every name GreyLine can actually HOLD must carry a sector, or it is a concentration blind spot the
    # risk limit can't see. This is the sleeves' actual tradeable sets — NOT the historical CSV dir,
    # which is the full-market point-in-time archive (thousands of names we never trade) and stopped
    # being "the traded universe" when survivorship archiving expanded it. The derived optionable
    # universe is kept mapped by app/scripts/build_sector_map.py (which now covers these sets) and any
    # held-but-unmapped name is surfaced at runtime (see test_unmapped_symbols_are_surfaced).
    from app.services.vrp_research_engine import VRPResearchEngine
    from app.services.trend_following_engine import TrendFollowingEngine
    from app.services.managed_futures_engine import ManagedFuturesEngine

    e = PortfolioExposureEngine()
    traded = (set(VRPResearchEngine.CURATED_FALLBACK)
              | set(TrendFollowingEngine.BASKET) | set(ManagedFuturesEngine.BASKET)
              | {"SGOV", "SVXY", "QQQM", "GLDM"})
    unmapped = sorted(s for s in traded if e._sector(s) == "UNKNOWN")
    assert unmapped == [], f"unmapped names in the traded universe: {unmapped}"


def test_entire_scan_universe_is_mapped():
    # A symbol added to the universe without a sector silently reopens the blind spot.
    import re

    universe = set(re.findall(r'"([A-Z]{1,5})"', UNIVERSE.read_text()))
    e = PortfolioExposureEngine()
    unmapped = sorted(s for s in universe if e._sector(s) == "UNKNOWN")
    assert unmapped == [], f"unmapped symbols in scan universe: {unmapped}"


def test_unmapped_symbols_are_surfaced(tmp_path):
    ledger = tmp_path / "eq.jsonl"
    ledger.write_text(json.dumps({
        "status": "OPEN", "symbol": "ZZZZ", "asset_type": "EQUITY",
        "quantity": 1, "entry_price": 10.0,
    }) + "\n")

    e = PortfolioExposureEngine()
    e.equity_ledger = ledger
    e.option_ledger = tmp_path / "none.jsonl"
    out = e.evaluate()

    assert out["unmapped_symbols"] == ["ZZZZ"]


# ---- market-closed decision guard ----
# The engine emitted thousands of EXECUTE decisions overnight on stale quotes. Nothing
# could fill, but each was recorded and captured as a forecast, feeding closed-market
# noise back into the regime trust stats the system judges itself by.

def test_no_execute_decision_when_market_is_closed():
    import app.services.greyline_master_decision_engine as md

    with patch.object(md, "MarketHoursEngine") as MockHours:
        MockHours.return_value.status.return_value = {
            "is_regular_session": False,
            "state": "MARKET_CLOSED",
        }
        out = md.GreyLineMasterDecisionEngine().evaluate()

    assert out["decision"] == "NO_ACTION"
    assert "Market is closed" in out["decision_reason"]
