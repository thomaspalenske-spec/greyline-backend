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

            "DIA": "BROAD_MARKET",
            "GLD": "PRECIOUS_METALS", "SLV": "PRECIOUS_METALS",
            "TLT": "TREASURIES",
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
        cached = getattr(cls, "_generated_sector_cache", None)
        if cached is None:
            try:
                cached = json.loads(Path("app/data/sector_map.json").read_text()).get("sectors") or {}
            except Exception:
                cached = {}     # absent or unreadable: degrade to the literal map, never crash
            cls._generated_sector_cache = cached
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
            "status": "PORTFOLIO_EXPOSURE_READY",
        }
