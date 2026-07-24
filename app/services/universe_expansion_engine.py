"""Build a universe that MIRRORS REALITY — every listed common stock, no quality screen.

Membership is a fact about EXISTENCE, not a judgement about liquidity, volatility or price.
An earlier version screened on today's dollar volume and applied that present-day fact
retroactively across 25 years: names quiet now were erased from the years they traded heavily,
and names liquid only since 2023 were inserted into 1999. That is look-ahead — the same error
as screening the universe on full-sample volatility — and it warps the reality the backtest is
supposed to describe.

Whether a name can be TRADED on a given day is a separate question, answered at DECISION time
from trailing data only (PriceBarTradabilityEngine's liquidity clip, the point-in-time
volatility ceiling, whole-share affordability). Those are rules executable live. A universe
screen is not.

REALITY GAP THAT REMAINS: this mirrors reality for LIVING companies only. Delisted names — the
~43% that disappeared since 2015 — are still absent, because their prices are unobtainable from
both TradeStation and UW. Closing that needs a paid survivorship-free vendor.

Sourcing: UW's /api/screener/stocks returns ticker, close, avg30_volume, marketcap, sector and
issue_type in bulk. It caps at 500 rows and its `page` param does not work, so the universe is
walked in MARKET-CAP BANDS (order desc + max_marketcap = previous band's floor). Verified to
produce zero overlap between bands.

HONEST COST OF EXPANDING (recorded here so it is not forgotten):
  * Survivorship bias gets WORSE down-cap. Small/mid caps delist far more often than large
    caps — most of the measured ~43% disappearance since 2015. Historical studies on an
    expanded universe are MORE inflated, not less. The forward PIT archive protects new data
    only.
  * A wider pool improves SELECTION (top-N drawn from more candidates) but does not change the
    $10k book's sizing; it does add more affordable names, which whole-share sizing likes.
  * Expansion is a HYPOTHESIS ("a wider universe improves the edge net of costs"), not a fact.
    It must be validated by re-running the backtest on the expanded set and comparing edge,
    Sharpe and breakeven against the current universe. If it only adds noise, revert.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path

import requests


class UniverseExpansionEngine:

    SCREENER = "https://api.unusualwhales.com/api/screener/stocks"
    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/research/universe_expansion_candidates.json")

    PAGE = 500                      # UW screener hard cap per request
    MAX_BANDS = 30                  # walk deep enough to reach the whole listed market

    # INCLUSION IS A FACT ABOUT EXISTENCE, NOT A JUDGEMENT ABOUT QUALITY.
    #
    # There is no liquidity, volatility or price screen here any more, and there must not be.
    # Screening membership on TODAY's liquidity applied a present-day fact retroactively across
    # 25 years of history — a stock quiet today was erased from 2010 when it was heavily
    # traded, and one liquid only since 2023 was inserted into 1999. That is look-ahead, the
    # same error as screening the universe on full-sample volatility.
    #
    # The universe must MIRROR REALITY: every listed common stock we can obtain history for.
    # Whether a name is TRADEABLE on any given day is a separate question, answered at decision
    # time from trailing data only:
    #   * PriceBarTradabilityEngine clips each symbol to when it actually became liquid
    #   * GREYLINE_MAX_TRAILING_VOL_PCT applies a point-in-time volatility ceiling
    #   * whole-share sizing drops names the book cannot afford
    # Those are real rules executable live. A universe screen is not.
    MIN_PRICE = 0.0                 # no price screen — penny stocks existed; PIT rules handle them
    TARGET_UNIVERSE = None          # no cap: take everything obtainable

    def _headers(self):
        return {"Authorization": f"Bearer {getenv('UNUSUAL_WHALES_API_KEY')}",
                "Accept": "application/json"}

    def _band(self, max_cap=None):
        params = {"limit": self.PAGE, "order": "marketcap", "order_direction": "desc"}
        if max_cap:
            params["max_marketcap"] = int(max_cap)
        try:
            r = requests.get(self.SCREENER, params=params, headers=self._headers(), timeout=60)
            if r.status_code != 200:
                return []
            return (r.json() or {}).get("data") or []
        except Exception:
            return []

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    LISTINGS = Path("app/data/research/universe/uw_listings_snapshot.json")

    def scan(self, save=True):
        """Every ACTIVE listed common stock — the membership question is 'does it exist?'.

        Sourced from the UW listings snapshot rather than the screener: the screener carries
        liquidity/market-cap data we deliberately no longer filter on, and its market-cap
        banding stalls on names with no cap data. Listings is the plain register of what is
        listed, which is exactly what membership should mirror.
        """
        tracked = {p.name.replace("_daily.csv", "") for p in self.HIST_DIR.glob("*_daily.csv")}
        try:
            snap = json.loads(self.LISTINGS.read_text())
        except Exception as e:
            return {"status": "NO_LISTINGS_SNAPSHOT", "error": str(e)[:120]}

        qualified, rejected = [], {"not_common_stock": 0, "not_us_exchange": 0,
                                   "derivative_ticker": 0, "delisted": 0}
        for r in snap.get("listings") or []:
            t = str(r.get("ticker") or "").upper()
            if not t:
                continue
            if str(r.get("status")) != "Active":
                rejected["delisted"] += 1        # unobtainable prices; see reality_gap
                continue
            if str(r.get("asset_type")) != "Stock":
                rejected["not_common_stock"] += 1
                continue
            if str(r.get("exchange")) not in ("NYSE", "NASDAQ", "NYSE MKT", "AMEX", "BATS"):
                rejected["not_us_exchange"] += 1
                continue
            # warrants / units / preferreds are different instruments, not a quality judgement
            if any(x in t for x in ("-WS", "-U", "-P", "-W", ".")):
                rejected["derivative_ticker"] += 1
                continue
            qualified.append({"ticker": t, "name": str(r.get("name") or "")[:48],
                              "ipo_date": str(r.get("ipo_date") or "")[:10],
                              "exchange": r.get("exchange"),
                              "already_tracked": t in tracked})

        qualified.sort(key=lambda q: q["ticker"])
        new = [q for q in qualified if not q["already_tracked"]]

        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "UW_LISTINGS_SNAPSHOT",
            "snapshot_fetched": str(snap.get("fetched_at") or "")[:10],
            "currently_tracked": len(tracked),
            "inclusion_rule": ("ACTIVE listed common stock on a US exchange — NO liquidity, "
                               "volatility, price or market-cap screen. Tradability is decided "
                               "point-in-time at each decision, never by editing membership."),
            "qualified_total": len(qualified),
            "qualified_already_tracked": len(qualified) - len(new),
            "recommended_additions": new,
            "recommended_addition_count": len(new),
            "rejected": rejected,
            "reality_gap": ("Mirrors reality for LIVING companies only. Delisted names (the "
                            "~43% that disappeared since 2015) remain absent — their prices are "
                            "unobtainable from TradeStation and UW alike and need a paid "
                            "survivorship-free vendor. That hole is NOT closed by this."),
            "status": "UNIVERSE_EXPANSION_CANDIDATES_READY",
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def last_scan(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
