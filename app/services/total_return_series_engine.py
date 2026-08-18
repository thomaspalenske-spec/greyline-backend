"""Build a dividend-and-split adjusted TOTAL-RETURN close for each symbol.

GreyLine's historical closes are split-adjusted but NOT dividend-adjusted — they are
price-only. Proven directly: Altria (MO) shows a 1.77%/yr CAGR over 28 years, impossible for
one of the era's best total-return stocks unless dividends are excluded. UW confirms it:
MO paid $146 of dividends against ~$29 of price change. Price-only returns systematically
understate every dividend payer, and each ex-dividend drop is a non-economic price fall that
the reversal leg can misread as a dip.

This engine layers the dividend adjustment on top of the already-split-adjusted price using
UW's dividend and split feeds, producing a parallel adjusted-close series. It does NOT touch
the raw CSVs — those are the validated, TradeStation-matched price series and stay the source
of truth for price. Total return is an additional column a backtest or signal can opt into.

THE ADJUSTMENT, AND THE TRAP IN IT:

  UW dividend amounts are RAW (as-paid). KO paid $0.51 in Jun-2012 and $0.2550 in Sep-2012 —
  that halving IS the 2:1 split, not a cut. Our prices are already split-adjusted, so a raw
  dividend divided by an adjusted price overstates every pre-split payout by the split factor
  (KO's 2011 ratio reads 1.45% vs the identical 2013 payout at 0.70%). Each dividend is
  therefore first divided by the cumulative split factor effective AFTER its ex-date, putting
  it on the same per-share basis as the price. Verified: this collapses KO's pre/post-split
  ratios to the same ~0.72%.

  The reinvestment factor on an ex-date is (1 - adj_div / close_before_ex). The adjusted close
  is the raw close scaled by the product of all factors for ex-dates STRICTLY AFTER that bar —
  the standard CRSP back-adjustment. The most recent bar is unadjusted (factor 1), so today's
  adjusted close equals today's real close, and history is scaled down to make returns
  continuous across ex-dates.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


class TotalReturnSeriesEngine:

    HIST_DIR = Path("app/data/historical")
    OUT_DIR = Path("app/data/historical_total_return")
    REPORT = Path("app/data/data_quality/total_return_build.json")

    # A distribution above this fraction of the prior close is not a normal cash dividend —
    # it is a spinoff/merger consideration that UW lists in the dividends feed. Even the
    # largest legitimate special cash dividends (MSFT 2004 ~10%) sit well under this, so 25%
    # excludes only the clear corporate actions.
    MAX_CASH_DIVIDEND_FRACTION = 0.25

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        if self._provider is None:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            self._provider = UnusualWhalesProvider()
        return self._provider

    # ------------------------------------------------------------ UW feeds

    def _dividends(self, ticker):
        """[(ex_date, raw_amount)] oldest->newest, or [] on any failure."""
        try:
            resp = self.provider._get(f"/api/companies/{ticker}/dividends")
            data = ((resp or {}).get("data") or {}).get("dividends") or []
        except Exception:
            return []
        out = []
        for d in data:
            ex = str(d.get("ex_date") or "")[:10]
            try:
                amt = float(d.get("amount"))
            except (TypeError, ValueError):
                continue
            if ex and amt > 0:
                out.append((ex, amt))
        return sorted(out)

    def _splits(self, ticker):
        """[(effective_date, split_factor)] oldest->newest, or []."""
        try:
            resp = self.provider._get(f"/api/companies/{ticker}/splits")
            data = ((resp or {}).get("data") or {}).get("splits") or []
        except Exception:
            return []
        out = []
        for s in data:
            eff = str(s.get("effective_date") or "")[:10]
            try:
                f = float(s.get("split_factor"))
            except (TypeError, ValueError):
                continue
            if eff and f > 0:
                out.append((eff, f))
        return sorted(out)

    @staticmethod
    def _cum_split_after(ex_date, splits):
        """Product of split factors effective STRICTLY AFTER ex_date.

        A dividend paid before a 2:1 split is $X/share on the old share count; in today's
        split-adjusted share basis (which the prices already use) it is $X/2. Dividing by the
        cumulative post-ex split factor puts the dividend on the price's basis.
        """
        factor = 1.0
        for eff, f in splits:
            if eff > ex_date:
                factor *= f
        return factor

    # --------------------------------------------------------------- build

    def _raw_rows(self, path):
        rows = []
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    try:
                        rows.append((str(r["date"])[:10], float(r["close"])))
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return []
        return rows

    def build_symbol(self, ticker, save=True):
        rows = self._raw_rows(self.HIST_DIR / f"{ticker}_daily.csv")
        if len(rows) < 30:
            return {"symbol": ticker, "status": "INSUFFICIENT_BARS", "bars": len(rows)}

        splits = self._splits(ticker)
        divs = self._dividends(ticker)
        dates = [d for d, _ in rows]
        closes = {d: c for d, c in rows}
        date_set = set(dates)

        # Split-adjust each dividend to the price basis, and pin it to the trading date it
        # applies to: the ex-date if it is a trading day, else the first trading day after.
        applied = []          # (trading_date, split_adjusted_amount)
        skipped = 0
        for ex, amt in divs:
            if ex < dates[0] or ex > dates[-1]:
                skipped += 1
                continue
            adj_amt = amt / self._cum_split_after(ex, splits)
            if ex in date_set:
                td = ex
            else:
                nxt = [d for d in dates if d > ex]
                if not nxt:
                    skipped += 1
                    continue
                td = nxt[0]
            applied.append((td, adj_amt))
        by_date = {}
        for td, a in applied:
            by_date[td] = by_date.get(td, 0.0) + a

        # Reinvestment factor per ex trading-date: 1 - div / close_of_PRIOR_bar.
        #
        # EXCLUDE implausibly large distributions. UW's dividend feed includes SPINOFF and
        # merger distributions valued at the spun-off entity — JCI shows an $88.53 "dividend"
        # on a $27.78 stock (319%), NI $27.59 on $16.99 (NiSource spinning off Columbia
        # Pipeline, 2015). Those are not reinvestable cash and cannot be adjusted without the
        # spinoff terms; treating them as cash collapsed whole histories to near zero and
        # produced a fake +177%/yr for JCI. Anything above MAX_CASH_DIVIDEND_FRACTION of the
        # prior close is recorded as a special distribution and left OUT of the cash
        # adjustment — visible, not silently mangled.
        idx = {d: i for i, d in enumerate(dates)}
        factor_on = {}
        special_distributions = []
        for td, a in by_date.items():
            i = idx[td]
            if i == 0:
                continue
            prev_close = rows[i - 1][1]
            if prev_close <= 0:
                continue
            frac = a / prev_close
            if frac > self.MAX_CASH_DIVIDEND_FRACTION:
                special_distributions.append(
                    {"date": td, "amount": round(a, 4), "prior_close": round(prev_close, 2),
                     "fraction_of_price": round(frac, 3)})
                continue
            factor_on[td] = 1.0 - frac

        # Back-adjust: adj_close[i] = close[i] * product(factor for ex-dates AFTER i).
        # Walk newest->oldest accumulating; the last bar keeps factor 1 so adj == real today.
        adj = [0.0] * len(rows)
        cum = 1.0
        for i in range(len(rows) - 1, -1, -1):
            adj[i] = rows[i][1] * cum
            d = dates[i]
            if d in factor_on:                 # this bar IS an ex-date: apply going further back
                cum *= factor_on[d]

        out_rows = list(zip(dates, (rows[i][1] for i in range(len(rows))), adj))
        if save:
            try:
                self.OUT_DIR.mkdir(parents=True, exist_ok=True)
                with open(self.OUT_DIR / f"{ticker}_total_return.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["date", "close", "adj_close"])
                    for d, c, a in out_rows:
                        w.writerow([d, f"{c:.6f}", f"{a:.6f}"])
            except Exception as e:
                return {"symbol": ticker, "status": "WRITE_FAILED", "error": str(e)[:120]}

        price_cagr = self._cagr(rows[0][1], rows[-1][1], dates[0], dates[-1])
        tr_cagr = self._cagr(adj[0], adj[-1], dates[0], dates[-1])
        return {
            "symbol": ticker,
            "status": "TOTAL_RETURN_BUILT",
            "bars": len(rows),
            "dividends_applied": len(factor_on),
            "dividends_out_of_range": skipped,
            "special_distributions_excluded": len(special_distributions),
            "special_distributions": special_distributions[:8],
            "splits": len(splits),
            "date_range": [dates[0], dates[-1]],
            "price_only_cagr_pct": price_cagr,
            "total_return_cagr_pct": tr_cagr,
            "dividend_contribution_pct_yr": (round(tr_cagr - price_cagr, 2)
                                             if tr_cagr is not None and price_cagr is not None
                                             else None),
        }

    @staticmethod
    def _cagr(p0, p1, d0, d1):
        try:
            yrs = (int(d1[:4]) + int(d1[5:7]) / 12) - (int(d0[:4]) + int(d0[5:7]) / 12)
            if yrs <= 0 or p0 <= 0 or p1 <= 0:
                return None
            return round(((p1 / p0) ** (1 / yrs) - 1) * 100, 2)
        except Exception:
            return None

    def build_universe(self, symbols=None, limit=None, save=True):
        syms = symbols or sorted(p.name.replace("_daily.csv", "")
                                 for p in self.HIST_DIR.glob("*_daily.csv"))
        if limit:
            syms = syms[:limit]
        built, failed = [], []
        for s in syms:
            r = self.build_symbol(s, save=save)
            (built if r.get("status") == "TOTAL_RETURN_BUILT" else failed).append(r)
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_built": len(built),
            "symbols_failed": len(failed),
            "total_dividends_applied": sum(r.get("dividends_applied", 0) for r in built),
            "examples": sorted(built, key=lambda r: -(r.get("dividend_contribution_pct_yr") or 0))[:15],
            "failed": failed[:20],
            "status": "TOTAL_RETURN_UNIVERSE_BUILT",
        }
        if save:
            try:
                self.REPORT.parent.mkdir(parents=True, exist_ok=True)
                self.REPORT.write_text(json.dumps(report, indent=2))
            except Exception:
                pass
        return report

    @staticmethod
    def _min_bars():
        try:
            from app.services.directional_signal_engine import DirectionalSignalEngine
            return DirectionalSignalEngine.MIN_BARS
        except Exception:
            return 253

    @staticmethod
    def _bars(path):
        try:
            with open(path) as f:
                return sum(1 for _ in f) - 1
        except Exception:
            return 0

    def _uncovered_eligible(self):
        """Sorted MIN_BARS-eligible universe names that lack a total-return file. Junk (warrants/units/
        micro-caps below MIN_BARS) is excluded — it never enters the momentum signal."""
        mb = self._min_bars()
        have = {p.name.replace("_total_return.csv", "").upper()
                for p in self.OUT_DIR.glob("*_total_return.csv")}
        elig, unc = 0, []
        for p in self.HIST_DIR.glob("*_daily.csv"):
            sym = p.name.replace("_daily.csv", "").upper()
            if self._bars(p) >= mb:
                elig += 1
                if sym not in have:
                    unc.append(sym)
        return sorted(unc), elig

    def coverage(self):
        """Total-return coverage of the TRADEABLE (>=MIN_BARS) momentum universe — the metric the armed
        GREYLINE_MOMENTUM_TOTAL_RETURN wiring depends on: an uncovered eligible name falls back to price-only
        and keeps its ex-div false reversals."""
        unc, elig = self._uncovered_eligible()
        cov = elig - len(unc)
        pct = round(cov / elig * 100, 1) if elig else None
        return {"min_bars": self._min_bars(), "eligible": elig, "covered": cov, "uncovered": len(unc),
                "coverage_pct": pct,
                "healthy": (pct is not None and pct >= 90.0),   # guard: a big gap = universe outran the build
                "uncovered_sample": unc[:25],
                "note": ("Total-return coverage of the tradeable (>=MIN_BARS) universe. Uncovered names fall "
                         "back to price-only under GREYLINE_MOMENTUM_TOTAL_RETURN and keep ex-div false "
                         "reversals; the scheduler builds a capped batch of any uncovered names once/day."),
                "status": "TOTAL_RETURN_COVERAGE"}

    def build_missing(self, limit=40):
        """Incrementally build total-return for up to `limit` uncovered-eligible names — the self-maintenance
        that stops coverage silently regrowing as the universe expands. Rate-limited by the provider."""
        todo = self._uncovered_eligible()[0][:max(0, int(limit))]
        built = failed = 0
        for s in todo:
            try:
                if self.build_symbol(s, save=True).get("status") == "TOTAL_RETURN_BUILT":
                    built += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"attempted": len(todo), "built": built, "failed": failed,
                "status": "TOTAL_RETURN_BUILD_MISSING"}

    def last_report(self):
        try:
            return json.loads(self.REPORT.read_text())
        except Exception:
            return None
