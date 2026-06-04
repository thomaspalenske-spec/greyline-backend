from datetime import datetime


class MarketUniverseEngine:

    def get_universe(self):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "universes": {
                "current_portfolio": [],
                "core_watchlist": [
                    "NVDA", "AMD", "PLTR", "TSM", "META",
                    "AMZN", "MSFT", "AVGO", "QQQ", "SPY"
                ],
                "apexion_core_universe": [
                    "SPY", "QQQ", "IWM", "NVDA", "TSLA",
                    "AMD", "META", "AAPL", "MSFT", "AVGO"
                ],
                "sector_etf_universe": [
                    "SMH", "XLK", "XLF", "XLE", "XLI",
                    "XLY", "XLV", "XLP", "XLU", "XLB"
                ],
                "futures_commodity_universe": [
                    "ES", "NQ", "CL", "GC"
                ],
                "crypto_linked_universe": [
                    "IBIT", "ETHE", "COIN", "MSTR"
                ]
            },
            "execution_enabled": False,
            "status": "MARKET_UNIVERSE_ACTIVE"
        }
