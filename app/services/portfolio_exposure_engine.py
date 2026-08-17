import json
from datetime import datetime
from os import getenv
from pathlib import Path


class PortfolioExposureEngine:
    # Concentration must be measured against the capital base, not against the
    # notional already deployed. Share-of-book is degenerate on a small book: a
    # single position is always 100% of the book, so a percent-of-book limit
    # hard-blocks every new entry the moment the first one fills.
    DEFAULT_CAPITAL_BASE = 10000.0

    def __init__(self):
        self.equity_ledger = Path("app/data/paper_trading/paper_trade_ledger.jsonl")
        self.option_ledger = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def _capital_base(self):
        try:
            base = float(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", self.DEFAULT_CAPITAL_BASE))
        except (TypeError, ValueError):
            base = self.DEFAULT_CAPITAL_BASE
        # A zero/negative base would divide the circuit breaker out of existence.
        return base if base > 0 else self.DEFAULT_CAPITAL_BASE

    def _read_jsonl(self, path):
        if not path.exists():
            return []

        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return rows

    def _sector(self, symbol):
        symbol = (symbol or "").upper().strip()

        sector_map = {
            "XLE": "ENERGY",
            "XLF": "FINANCIALS",
            "XLU": "UTILITIES",
            "XLK": "TECHNOLOGY",
            "XLY": "CONSUMER_DISCRETIONARY",
            "XLP": "CONSUMER_STAPLES",
            "XLI": "INDUSTRIALS",
            "XLV": "HEALTHCARE",
            "XLB": "MATERIALS",
            "XLRE": "REAL_ESTATE",
            "XLC": "COMMUNICATIONS",
            "QQQ": "TECH_GROWTH",
            "SPY": "BROAD_MARKET",
            "IWM": "SMALL_CAP",
            "NVDA": "TECHNOLOGY",
            "AMD": "TECHNOLOGY",
            "AVGO": "TECHNOLOGY",
            "MSFT": "TECHNOLOGY",
            "META": "COMMUNICATIONS",
            "AMZN": "CONSUMER_DISCRETIONARY",
            "TSM": "TECHNOLOGY",
            "PLTR": "TECHNOLOGY",
            "AAPL": "TECHNOLOGY",
            "SMH": "TECHNOLOGY",
            "TSLA": "CONSUMER_DISCRETIONARY",

            # Crypto. These four are one bet, not four: a spot bitcoin ETF, the exchange,
            # an ether trust, and a company whose equity is a levered bitcoin proxy. They
            # were all falling through to UNKNOWN, so a book that was 40% long bitcoin
            # four different ways read as diversified to the concentration limit.
            "IBIT": "CRYPTO",
            "COIN": "CRYPTO",
            "ETHE": "CRYPTO",
            "MSTR": "CRYPTO",

            # Index futures track the ETFs we already hold, so they must share a bucket
            # with them or index exposure gets double-counted as two "sectors".
            "ES": "BROAD_MARKET",
            "NQ": "TECH_GROWTH",

            "CL": "ENERGY",
            "GC": "PRECIOUS_METALS",

            # Full scan-universe coverage. The momentum-reversal strategy trades all 98
            # names, so an unmapped name is a real concentration blind spot — correlated
            # positions could stack while the limit reads them as diversified. Grouped by
            # what actually moves together, not strict GICS (e.g. big-box retail together,
            # defense primes under industrials, semis under technology).
            "ADBE": "TECHNOLOGY", "CRM": "TECHNOLOGY", "CSCO": "TECHNOLOGY",
            "INTC": "TECHNOLOGY", "ORCL": "TECHNOLOGY", "QCOM": "TECHNOLOGY",
            "SHOP": "TECHNOLOGY", "SNOW": "TECHNOLOGY", "TXN": "TECHNOLOGY",
            "UBER": "TECHNOLOGY",

            "AXP": "FINANCIALS", "BAC": "FINANCIALS", "C": "FINANCIALS",
            "GS": "FINANCIALS", "JPM": "FINANCIALS", "KRE": "FINANCIALS",
            "MA": "FINANCIALS", "MS": "FINANCIALS", "V": "FINANCIALS",
            "WFC": "FINANCIALS",
            # Stragglers pinned deliberately (the API-frugal daily refresh reuses the OI top-500 + one
            # marketcap top-500, and these S&P mid-caps sit below both slices — large ETFs fill the
            # marketcap top). MMC (Marsh, insurance); SQ (Block, retired ticker); BIIB (Biogen); DG
            # (Dollar General, discount staples). The fail-loud sector test catches any future drift.
            "MMC": "FINANCIALS", "SQ": "FINANCIALS", "BIIB": "HEALTHCARE", "DG": "CONSUMER_STAPLES",

            "ABBV": "HEALTHCARE", "ABT": "HEALTHCARE", "DHR": "HEALTHCARE",
            "IBB": "HEALTHCARE", "JNJ": "HEALTHCARE", "LLY": "HEALTHCARE",
            "MRK": "HEALTHCARE", "PFE": "HEALTHCARE", "TMO": "HEALTHCARE",
            "UNH": "HEALTHCARE",

            "BA": "INDUSTRIALS", "CAT": "INDUSTRIALS", "DE": "INDUSTRIALS",
            "GE": "INDUSTRIALS", "HON": "INDUSTRIALS", "LMT": "INDUSTRIALS",
            "NOC": "INDUSTRIALS", "RTX": "INDUSTRIALS",

            "COP": "ENERGY", "CVX": "ENERGY", "EOG": "ENERGY",
            "SLB": "ENERGY", "USO": "ENERGY", "XOM": "ENERGY",

            "ABNB": "CONSUMER_DISCRETIONARY", "HD": "CONSUMER_DISCRETIONARY",
            "LOW": "CONSUMER_DISCRETIONARY", "MCD": "CONSUMER_DISCRETIONARY",
            "NKE": "CONSUMER_DISCRETIONARY", "SBUX": "CONSUMER_DISCRETIONARY",

            "COST": "CONSUMER_STAPLES", "KO": "CONSUMER_STAPLES",
            "MO": "CONSUMER_STAPLES", "PEP": "CONSUMER_STAPLES",
            "PG": "CONSUMER_STAPLES", "PM": "CONSUMER_STAPLES",
            "TGT": "CONSUMER_STAPLES", "WMT": "CONSUMER_STAPLES",

            "AEP": "UTILITIES", "DUK": "UTILITIES", "NEE": "UTILITIES",
            "SO": "UTILITIES",

            "CMCSA": "COMMUNICATIONS", "DIS": "COMMUNICATIONS",
            "GOOG": "COMMUNICATIONS", "GOOGL": "COMMUNICATIONS",
            "NFLX": "COMMUNICATIONS",

            "DIA": "BROAD_MARKET", "VTI": "BROAD_MARKET",
            "GLD": "PRECIOUS_METALS", "SLV": "PRECIOUS_METALS",
            "PPLT": "PRECIOUS_METALS",
            "TLT": "TREASURIES",
            # Multi-asset ETFs added 2026-07-21. Bucketed by asset class so the
            # concentration limit SEES them: without these, six bond ETFs or five
            # commodity trackers would each pool into UNKNOWN and read as diversified while
            # being one correlated bet — the exact concentration-blindness the sector map
            # exists to prevent. Rates ETFs share a bucket because they move on one factor
            # (the curve); commodities span sub-groups but are one asset-class exposure at
            # $10k sizing.
            "IEF": "TREASURIES", "SHY": "TREASURIES", "TIP": "TREASURIES",
            "AGG": "BONDS_CREDIT", "LQD": "BONDS_CREDIT", "HYG": "BONDS_CREDIT",
            "DBC": "COMMODITIES", "DBA": "COMMODITIES", "UNG": "COMMODITIES",
            "CPER": "COMMODITIES",
            "EFA": "INTL_EQUITY", "EEM": "INTL_EQUITY", "VWO": "INTL_EQUITY",
            "FXI": "INTL_EQUITY", "EWJ": "INTL_EQUITY", "EWZ": "INTL_EQUITY",

            # Traded-universe ETFs beyond the original scan list (the derived optionable universe + the
            # ETF sleeves). UW does NOT sector-classify funds, so they are bucketed HERE by the exposure
            # that actually moves them — otherwise each pools into UNKNOWN and reads as diversified.
            "QQQM": "TECH_GROWTH", "TQQQ": "TECH_GROWTH", "SQQQ": "TECH_GROWTH",   # Nasdaq-100 (± leverage)
            "NVDL": "TECHNOLOGY", "SOXX": "TECHNOLOGY", "SOXL": "TECHNOLOGY",      # single-name/semis
            "IGV": "TECHNOLOGY",                                                  # software
            "TSLL": "CONSUMER_DISCRETIONARY",                                     # 2x Tesla
            "ARKK": "TECH_GROWTH", "ARKG": "TECH_GROWTH",                         # innovation/growth
            "RSP": "BROAD_MARKET",                                               # S&P 500 equal weight
            # VIX-futures products — long OR short, they are ONE factor (the VIX curve). Grouped so the
            # cap sees them as a single bet, not several comfortable-looking ones.
            "SVXY": "VOLATILITY", "VXX": "VOLATILITY", "VXZ": "VOLATILITY", "UVXY": "VOLATILITY",
            "UVIX": "VOLATILITY", "SVIX": "VOLATILITY", "VIXY": "VOLATILITY", "VIXM": "VOLATILITY",
            "BITW": "CRYPTO",                                                    # crypto index fund
            "XBI": "HEALTHCARE", "MSOS": "HEALTHCARE",                           # biotech / cannabis
            "XOP": "ENERGY", "BNO": "ENERGY", "URA": "ENERGY",                   # oil E&P / Brent / uranium
            "GDX": "PRECIOUS_METALS", "SILJ": "PRECIOUS_METALS",                 # gold / silver miners
            "GLDM": "PRECIOUS_METALS",                                           # gold (sleeve)
            "COPX": "MATERIALS",                                                 # copper miners
            "CORN": "COMMODITIES",                                              # grain futures
            "ETHA": "CRYPTO",                                                    # spot ether
            "KWEB": "INTL_EQUITY", "ASHR": "INTL_EQUITY", "EWC": "INTL_EQUITY",  # China / Canada
            "EWY": "INTL_EQUITY", "KORU": "INTL_EQUITY",                         # South Korea (± leverage)
            "SGOV": "TREASURIES",                                                # 0-3mo T-bills (cash sweep)
            "DRAM": "TECHNOLOGY", "SNXX": "TECHNOLOGY",                          # memory-chip / 2x-SanDisk ETFs
        }

        if symbol in sector_map:
            return sector_map[symbol]
        # Fall back to the generated map (app/scripts/build_sector_map.py). The literal
        # above covers the ETFs and predates the universe; the generated file covers the
        # S&P 500 names added on 2026-07-19, 9 of whose first 10 selections resolved to
        # UNKNOWN and so pooled into one meaningless bucket the sector cap could not see.
        # Hand-written entries win: they are the deliberate ones.
        return self._generated_sectors().get(symbol, "UNKNOWN")

    @classmethod
    def _generated_sectors(cls):
        # Resolve the map by MODULE location, not cwd — a cwd-relative path silently read empty
        # whenever the process ran from elsewhere (e.g. the sandboxed test cwd), dropping every
        # UW-generated name to UNKNOWN and blinding the concentration cap.
        try:
            path = Path(__file__).resolve().parents[2] / "app" / "data" / "sector_map.json"
            mtime = path.stat().st_mtime
        except Exception:
            path, mtime = None, None
        # RELOAD when the file changes: the map is regenerated once/day, but this in-process cache used to
        # be held for the whole process lifetime, so a refreshed sector map was never picked up without a
        # restart — silently classifying concentration off a stale map. Key the cache on the file mtime.
        cached = getattr(cls, "_generated_sector_cache", None)
        if cached is None or mtime != getattr(cls, "_generated_sector_mtime", None):
            try:
                cached = json.loads(path.read_text()).get("sectors") or {}
            except Exception:
                cached = {}     # absent or unreadable: degrade to the literal map, never crash
            cls._generated_sector_cache = cached
            cls._generated_sector_mtime = mtime
        return cached

    def _notional(self, trade):
        qty = float(trade.get("quantity") or trade.get("contracts") or 0)
        price = float(
            trade.get("current_price")
            or trade.get("entry_price")
            or 0
        )

        multiplier = 100 if trade.get("asset_type") == "OPTION" else 1
        return round(abs(qty * price * multiplier), 2)

    def _broker_positions(self):
        """Live broker holdings, aggregated by underlying — the ACTUAL exposure. The ETF sleeves
        (vol-carry / trend / managed-futures / T-bill) book STRAIGHT to the broker, not the paper
        ledgers, so without this the concentration cap is blind to them. Same source Open Positions uses;
        market_value isn't populated in the snapshot, so notional is computed from qty x mark.

        Returns (rows, degraded). `degraded` is True when the broker read FAILED (reads_ok False or an
        exception) — distinct from an empty book. A degraded read means the ETF-sleeve holdings are
        UNKNOWN, not zero, so the caller must fail closed rather than report a falsely-clean, low
        concentration computed from the paper ledgers alone."""
        agg = {}
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            view = BrokerAccountViewEngine().snapshot()
            if not view.get("reads_ok", True):
                return [], True
            try:
                from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
                cash_sweep = TbillCashSweepEngine.symbol()      # SGOV = parked CASH, not a treasury bet
            except Exception:
                cash_sweep = "SGOV"
            for p in (view.get("positions") or []):
                raw = str(p.get("symbol") or "")
                under = (raw.split() or [""])[0].upper()      # OSI option symbols carry spaces
                if not under or under == str(cash_sweep).upper():
                    continue                                  # cash-equivalent: not a sector-risk concentration
                qty = float(p.get("quantity") or 0)
                price = float(p.get("current_price") or 0)
                is_opt = (p.get("asset_type") == "OPTION") or (" " in raw)
                notional = abs(qty * price * (100 if is_opt else 1))
                e = agg.setdefault(under, {"symbol": under,
                                           "asset_type": "OPTION" if is_opt else "EQUITY", "notional": 0.0})
                e["notional"] += notional
                if is_opt:
                    e["asset_type"] = "OPTION"
        except Exception:
            return [], True
        for e in agg.values():
            e["notional"] = round(e["notional"], 2)
        return list(agg.values()), False

    def evaluate(self):
        equity_rows = self._read_jsonl(self.equity_ledger)
        option_rows = self._read_jsonl(self.option_ledger)

        open_positions = []

        for row in equity_rows:
            if row.get("status") == "OPEN":
                symbol = row.get("symbol")
                open_positions.append({
                    "symbol": symbol,
                    "asset_type": row.get("asset_type", "EQUITY"),
                    "sector": self._sector(symbol),
                    "notional": self._notional(row),
                    "directional_bias": row.get("directional_bias"),
                    "status": row.get("status"),
                })

        for row in option_rows:
            if row.get("status") == "OPEN":
                symbol = row.get("underlying") or row.get("symbol")
                open_positions.append({
                    "symbol": symbol,
                    "asset_type": "OPTION",
                    "sector": self._sector(symbol),
                    "notional": self._notional(row),
                    "directional_bias": row.get("directional_bias"),
                    "status": row.get("status"),
                })

        # ADD live broker holdings the paper ledgers don't carry (the ETF sleeves), deduped by symbol so
        # a name already in a ledger is never counted twice. This makes the concentration cap reflect
        # ACTUAL broker exposure — the same holdings the Open Positions card shows — not just the paper book.
        ledger_syms = {p["symbol"] for p in open_positions if p["symbol"]}
        broker_rows, broker_degraded = self._broker_positions()
        for bp in broker_rows:
            if bp["symbol"] and bp["symbol"] not in ledger_syms:
                open_positions.append({
                    "symbol": bp["symbol"], "asset_type": bp["asset_type"],
                    "sector": self._sector(bp["symbol"]), "notional": bp["notional"],
                    "directional_bias": None, "status": "OPEN", "source": "BROKER",
                })

        total_notional = round(sum(p["notional"] for p in open_positions), 2)

        sector_exposure = {}
        for p in open_positions:
            sector = p["sector"]
            sector_exposure.setdefault(sector, 0.0)
            sector_exposure[sector] += p["notional"]

        capital_base = self._capital_base()

        sector_exposure = {
            k: {
                "notional": round(v, 2),
                # Share of the open book — what dominates the portfolio right now.
                # Used for composition/exit prioritization, NOT for the hard limit.
                "pct_of_portfolio": round((v / total_notional) * 100, 2) if total_notional else 0,
                # Share of the account's capital — what the risk limit is about.
                "pct_of_capital": round((v / capital_base) * 100, 2),
            }
            for k, v in sorted(sector_exposure.items())
        }

        max_sector_pct_of_book = max(
            [v["pct_of_portfolio"] for v in sector_exposure.values()],
            default=0,
        )

        # The limit engines consume max_sector_exposure_pct. It must be
        # capital-relative so that concentration is measured against what the
        # account can deploy, not against what it happens to hold.
        max_sector_pct = max(
            [v["pct_of_capital"] for v in sector_exposure.values()],
            default=0,
        )

        if max_sector_pct >= 50:
            concentration_risk = "HIGH"
        elif max_sector_pct >= 35:
            concentration_risk = "ELEVATED"
        elif max_sector_pct >= 20:
            concentration_risk = "MODERATE"
        else:
            concentration_risk = "LOW"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioExposureEngine",
            # When the broker read failed, the ETF-sleeve holdings are UNKNOWN (not zero) — the
            # concentration numbers below are computed from the paper ledgers ALONE and understate real
            # exposure. Surface it so the hard limit engine can fail closed instead of reading a
            # falsely-clean book. reads_ok True only when the live broker holdings were actually seen.
            "reads_ok": not broker_degraded,
            "degraded": broker_degraded,
            "open_position_count": len(open_positions),
            "total_notional": total_notional,
            "capital_base": capital_base,
            # An unmapped symbol is a concentration blind spot, not a harmless default:
            # everything unclassified pools into one "UNKNOWN" bucket that means nothing,
            # so correlated names can stack up while the limit reads them as diversified.
            # Surface them rather than letting the next universe addition do this quietly.
            "unmapped_symbols": sorted(
                {p["symbol"] for p in open_positions if p["sector"] == "UNKNOWN" and p["symbol"]}
            ),
            "sector_exposure": sector_exposure,
            "max_sector_exposure_pct": max_sector_pct,
            "max_sector_exposure_pct_of_book": max_sector_pct_of_book,
            "concentration_risk": concentration_risk,
            "positions": open_positions,
            "status": "PORTFOLIO_EXPOSURE_DEGRADED" if broker_degraded else "PORTFOLIO_EXPOSURE_READY",
        }
