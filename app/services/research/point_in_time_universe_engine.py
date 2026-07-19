"""Survivorship-free, point-in-time tradable universe built from Unusual Whales listings.

The live strategy's universe is whatever *_daily.csv files sit in app/data/historical — 98
hand-picked mega-caps and sector ETFs, chosen once in June 2026. Every backtest run against
it is survivorship-biased twice over: the list contains only names that were worth picking
in 2026, and it contains no company that failed.

UW's /api/companies/listings carries ipo_date and delisting_date for both active and
delisted securities, which is enough to answer "was this tradable on date D" directly — no
index-membership subscription required. A ticker is in the universe on D when
    ipo_date <= D  and  (delisting_date is null or D < delisting_date)

COVERAGE LIMIT — READ BEFORE TRUSTING A RESULT:
UW's delisted coverage effectively begins in 2013. Only 261 delisted stocks carry a
delisting_date before 2013, and the dot-com bust and the GFC show almost none, which cannot
be a real delisting rate. Before 2013 this universe is therefore still survivorship-biased
and must not be used. EARLIEST_TRUSTWORTHY_DATE encodes that; resolve() refuses earlier
dates rather than quietly returning a flattering universe.

Writes only under app/data/research/. Never into app/data/historical — that directory IS
the live tradable universe (MomentumReversalStrategyEngine._symbols globs it), so a research
download landing there would silently put untested names into tomorrow's book.
"""

import json
import re
from datetime import datetime
from pathlib import Path

RESEARCH_DIR = Path("app/data/research/universe")
SNAPSHOT = RESEARCH_DIR / "uw_listings_snapshot.json"

# Before this, UW's delisted coverage is too sparse to be survivorship-free (see above).
EARLIEST_TRUSTWORTHY_DATE = "2013-01-01"

_NULLS = (None, "", "null", "None")

# UW types preferreds, warrants, units and rights as asset_type "Stock", so ~8% of a raw
# universe is not common equity at all. A momentum signal on a preferred share measures
# interest rates, and a warrant's leverage manufactures fake momentum — both would pollute
# the ranking. Suffix conventions: -P-x preferred, -WS/-W warrant or when-issued, -U unit,
# -R/-RT rights. A bare single-letter suffix (AGM-A, BRK-B) is a real dual-class common
# share and is KEPT.
_DERIVATIVE_SUFFIX = re.compile(r"-(P(-|$)|WS|W$|U$|R$|RT$|CL$)")

# Corporate bonds leak in as "Stock" too ("ASRV 8.45 06-30-28") — they always carry spaces.
_BOND = re.compile(r"\s")

# NASDAQ's fifth-letter convention: a 5-letter ticker ending W/U/R is a warrant, unit or
# right (ABEOW = ABEO warrants). Deliberately NOT excluding Q — Q means the issuer is in
# bankruptcy, and AAMRQ (AMR Corp) is common stock that later went to zero. Dropping the Qs
# would re-introduce precisely the survivorship bias this engine exists to remove.
_FIFTH_LETTER_DERIVATIVE = re.compile(r"^[A-Z]{4}[WUR]$")


class PointInTimeUniverseEngine:

    def __init__(self, snapshot_path=SNAPSHOT):
        self.snapshot_path = Path(snapshot_path)

    # ---- acquisition -------------------------------------------------------
    def refresh_snapshot(self, provider=None):
        """Pull active + delisted listings from UW and persist them. Two API calls."""
        if provider is None:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            provider = UnusualWhalesProvider()

        def fetch(status):
            resp = provider._get("/api/companies/listings", params={"status": status})
            return ((resp or {}).get("data") or {}).get("listings") or []

        # Dated queries 403 beyond the plan's lookback, but the undated call returns the
        # full list with per-row dates, which is all the resolver needs.
        rows = fetch("active") + fetch("delisted")
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.write_text(json.dumps({
            "fetched_at": datetime.utcnow().isoformat(),
            "count": len(rows),
            "listings": rows,
        }))
        return {"fetched_at": datetime.utcnow().isoformat(), "listings": len(rows),
                "path": str(self.snapshot_path), "status": "UNIVERSE_SNAPSHOT_WRITTEN"}

    def _listings(self):
        return json.loads(self.snapshot_path.read_text()).get("listings") or []

    # ---- resolution --------------------------------------------------------
    @staticmethod
    def _date(value):
        if value in _NULLS:
            return None
        return str(value)[:10]

    def resolve(self, as_of, asset_types=("Stock",), exchanges=None, common_only=True):
        """Tickers tradable on `as_of` (ISO date), survivorship-free.

        A name that later delisted IS included for the dates it was still listed — that is
        the whole point. Raises on dates before EARLIEST_TRUSTWORTHY_DATE rather than
        returning a universe whose failures are missing.
        """
        as_of = str(as_of)[:10]
        if as_of < EARLIEST_TRUSTWORTHY_DATE:
            raise ValueError(
                f"{as_of} precedes {EARLIEST_TRUSTWORTHY_DATE}: UW delisted coverage is too "
                "sparse before 2013 to be survivorship-free (261 delisted stocks total, "
                "with the dot-com bust and GFC effectively absent). Buy point-in-time data "
                "from Norgate or Sharadar to study that period."
            )
        out = []
        for row in self._listings():
            if asset_types and str(row.get("asset_type")) not in asset_types:
                continue
            if exchanges and str(row.get("exchange")) not in exchanges:
                continue
            ipo = self._date(row.get("ipo_date"))
            delisted = self._date(row.get("delisting_date"))
            if ipo and ipo > as_of:
                continue                    # not yet public
            if delisted and delisted <= as_of:
                continue                    # already gone
            ticker = row.get("ticker")
            if not ticker:
                continue
            if common_only and (_DERIVATIVE_SUFFIX.search(ticker)
                                or _BOND.search(ticker)
                                or _FIFTH_LETTER_DERIVATIVE.match(ticker)):
                continue
            out.append(ticker)
        return sorted(set(out))

    def survivorship_check(self, as_of):
        """How many names in the as_of universe are dead today — the bias being removed.

        A curated present-day list would report 0: that is exactly the flaw. A healthy
        historical universe should carry a meaningful share of eventual failures.
        """
        live = set(self.resolve(as_of))
        today = set(self.resolve(datetime.utcnow().date().isoformat()))
        dead = sorted(live - today)
        return {"as_of": as_of, "universe": len(live), "since_delisted": len(dead),
                "pct_since_delisted": round(100 * len(dead) / len(live), 2) if live else 0.0,
                "examples": dead[:15], "status": "SURVIVORSHIP_CHECK_COMPLETE"}
