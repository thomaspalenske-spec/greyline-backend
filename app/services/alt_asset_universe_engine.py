"""Alt-asset universe — the three whole classes TradeStation trades that GreyLine had NO position in
(2026-08-12 scan): long-vol / VIX ETPs, direct FUTURES, and spot FX.

Same discipline as the extended ETF universe: this ADDS them as TRACKED CANDIDATES with backfilled bars —
it does NOT arm anything. Two tiers of readiness, because the classes differ:
  * vol_etp  — VXX/VIXY/UVXY/UVIX/SVIX are ordinary equity ETPs; GreyLine's existing equity execution can
    already trade them, so `tradeable_now=True`. Their bars go to the equity store (app/data/historical),
    excluded from the single-stock momentum factor like every other ETF.
  * futures / fx — genuinely NEW instrument classes: continuous futures (@ROOT: margin, roll, tick value,
    contract sizing) and spot FX (pip/lot, no options). `tradeable_now=False` — each needs its OWN execution
    plumbing before a dollar trades. Their bars go to a SEPARATE store (app/data/alt_assets) so they never
    touch the equity universe. Registered + bar-backfilled = measurable candidates, not tradeable positions.

caution = leveraged/inverse decay products (UVXY 1.5x, UVIX 2x, SVIX -1x) — registered, never for a sleeve.
"""

import csv
from datetime import datetime
from os import getenv
from pathlib import Path


class AltAssetUniverseEngine:

    EQUITY_STORE = Path("app/data/historical")            # vol ETPs live here (they're equities)
    ALT_STORE = Path("app/data/alt_assets")               # futures + FX live here (NOT the equity universe)
    REFRESH_MARK = ALT_STORE / ".last_refresh"            # once/UTC-day append-only refresh marker

    # symbol -> (asset_class, ts_symbol, tradeable_now, caution)
    UNIVERSE = {
        # long-vol / VIX ETPs — ordinary equity ETPs, tradeable via existing equity execution
        "VXX":  ("vol_etp", "VXX",  True,  False),
        "VIXY": ("vol_etp", "VIXY", True,  False),
        "UVXY": ("vol_etp", "UVXY", True,  True),         # 1.5x long-vol — decay, caution
        "UVIX": ("vol_etp", "UVIX", True,  True),         # 2x long-vol — decay, caution
        "SVIX": ("vol_etp", "SVIX", True,  True),         # -1x short-vol — caution
        # direct futures — continuous @ROOT (TS legacy roots); NEW class, needs futures execution plumbing
        # index
        "ES":  ("futures", "@ES",  False, False), "NQ": ("futures", "@NQ", False, False),
        "RTY": ("futures", "@RTY", False, False), "YM": ("futures", "@YM", False, False),
        # rates: @US 30y · @TY 10y · @FV 5y · @TU 2y
        "US":  ("futures", "@US",  False, False), "TY": ("futures", "@TY", False, False),
        "FV":  ("futures", "@FV",  False, False), "TU": ("futures", "@TU", False, False),
        # energy
        "CL":  ("futures", "@CL",  False, False), "NG": ("futures", "@NG", False, False),
        "RB":  ("futures", "@RB",  False, False),
        # metals
        "GC":  ("futures", "@GC",  False, False), "SI": ("futures", "@SI", False, False),
        "HG":  ("futures", "@HG",  False, False), "PL": ("futures", "@PL", False, False),
        # grains: @C corn · @S soybeans · @W wheat
        "C":   ("futures", "@C",   False, False), "S":  ("futures", "@S",  False, False),
        "W":   ("futures", "@W",   False, False),
        # vol
        "VX":  ("futures", "@VX",  False, False),
        # spot FX — NEW class, needs FX execution plumbing
        "EURUSD": ("fx", "EURUSD", False, False), "USDJPY": ("fx", "USDJPY", False, False),
        "GBPUSD": ("fx", "GBPUSD", False, False), "AUDUSD": ("fx", "AUDUSD", False, False),
        "USDCAD": ("fx", "USDCAD", False, False), "USDCHF": ("fx", "USDCHF", False, False),
    }

    @classmethod
    def all(cls):
        return [{"key": k, "asset_class": a, "ts_symbol": t, "tradeable_now": tn, "caution": c}
                for k, (a, t, tn, c) in cls.UNIVERSE.items()]

    @classmethod
    def by_class(cls):
        out = {}
        for k, (a, t, tn, c) in cls.UNIVERSE.items():
            out.setdefault(a, []).append(k)
        return {a: sorted(v) for a, v in sorted(out.items())}

    @classmethod
    def symbols(cls, asset_class=None, tradeable_only=False, include_caution=True):
        return [k for k, (a, t, tn, c) in cls.UNIVERSE.items()
                if (asset_class is None or a == asset_class)
                and (not tradeable_only or tn) and (include_caution or not c)]

    @classmethod
    def vol_etp_symbols(cls, include_caution=True):
        """The equity vol ETPs — for the momentum-exclusion + quote-stream tracking (they're in the equity store)."""
        return cls.symbols(asset_class="vol_etp", include_caution=include_caution)

    @classmethod
    def _store_for(cls, asset_class):
        return cls.EQUITY_STORE if asset_class == "vol_etp" else cls.ALT_STORE

    @classmethod
    def bar_path(cls, key):
        meta = cls.UNIVERSE.get(key)
        if not meta:
            return None
        a = meta[0]
        return cls._store_for(a) / (f"{key}_daily.csv")

    @classmethod
    def snapshot(cls):
        return {
            "count": len(cls.UNIVERSE),
            "by_class": cls.by_class(),
            "tradeable_now": cls.symbols(tradeable_only=True),
            "needs_plumbing": [k for k, (a, t, tn, c) in cls.UNIVERSE.items() if not tn],
            "instruments": cls.all(),
            "note": ("TRACKED CANDIDATES with backfilled bars — NOT armed. vol ETPs are tradeable via existing "
                     "equity execution; futures (@ROOT continuous) + spot FX are NEW classes that each need "
                     "their own execution plumbing (margin/roll/tick for futures; pip/lot for FX) before a "
                     "dollar trades. Nothing here deploys capital."),
            "status": "ALT_ASSET_UNIVERSE",
        }

    # ---- backfill (reusable) --------------------------------------------------------------------
    @classmethod
    def backfill(cls, bars_back=2000, only_missing=True):
        """Fetch daily bars for each instrument via its TS symbol and write to the right store. Additive;
        skips a symbol whose file exists (only_missing). Returns a per-symbol report. Never fabricates."""
        import requests
        from app.services.env_reload import reload_env
        from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
        import time as _t
        reload_env()
        TradeStationTokenMaintenanceEngine().evaluate()
        tok = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com").rstrip("/")
        if not tok:
            return {"status": "ALT_BACKFILL_NO_TOKEN"}
        cls.EQUITY_STORE.mkdir(parents=True, exist_ok=True)
        cls.ALT_STORE.mkdir(parents=True, exist_ok=True)
        ok, skipped, failed = [], [], []
        for key, (a, ts_sym, tn, c) in cls.UNIVERSE.items():
            path = cls.bar_path(key)
            if only_missing and path.exists():
                skipped.append(key); continue
            try:
                r = requests.get(f"{base}/v3/marketdata/barcharts/{ts_sym}",
                                 params={"unit": "Daily", "barsback": bars_back},
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                                 timeout=(5, 25))
                if r.status_code != 200:
                    failed.append((key, "http %s" % r.status_code)); _t.sleep(0.35); continue
                rows = []
                for b in (r.json() or {}).get("Bars", []) or []:
                    tsx = b.get("TimeStamp") or b.get("Timestamp")
                    try:
                        o = float(b.get("Open")); h = float(b.get("High")); lo = float(b.get("Low")); cl = float(b.get("Close"))
                        v = int(float(b.get("TotalVolume") or b.get("Volume") or 0))
                    except (TypeError, ValueError):
                        continue
                    if tsx and cl > 0:
                        rows.append((str(tsx)[:10], o, h, lo, cl, v))
                rows.sort(key=lambda x: x[0])
                if len(rows) < 30:
                    failed.append((key, "too-few-bars %d" % len(rows))); _t.sleep(0.35); continue
                with open(path, "w", newline="") as f:
                    w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "volume"]); w.writerows(rows)
                ok.append((key, len(rows), rows[0][0], rows[-1][0]))
            except Exception as e:
                failed.append((key, repr(e)[:60]))
            _t.sleep(0.35)
        return {"status": "ALT_BACKFILL_DONE", "wrote": len(ok), "skipped": len(skipped),
                "failed": failed, "written": ok}

    @classmethod
    def refresh_if_due(cls):
        """Append-only refresh of the alt-asset bars, at most ONCE per UTC day (so the futures/FX signal
        stays current — the app/data/historical daily remediation doesn't touch this store)."""
        today = datetime.utcnow().date().isoformat()
        try:
            if cls.REFRESH_MARK.exists() and cls.REFRESH_MARK.read_text().strip() == today:
                return {"status": "ALT_REFRESH_NOT_DUE", "date": today}
        except Exception:
            pass
        r = cls.refresh()
        try:
            cls.ALT_STORE.mkdir(parents=True, exist_ok=True)
            cls.REFRESH_MARK.write_text(today)
        except Exception:
            pass
        return r

    @classmethod
    def refresh(cls, recent_bars=15):
        """Append-only: fetch the last `recent_bars` daily bars per instrument and MERGE by date into the
        existing CSV (new dates appended, recent few refreshed) — never removes settled history. Only
        refreshes instruments already backfilled. Best-effort per symbol."""
        import requests
        from app.services.env_reload import reload_env
        from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
        import time as _t
        reload_env()
        TradeStationTokenMaintenanceEngine().evaluate()
        tok = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com").rstrip("/")
        if not tok:
            return {"status": "ALT_REFRESH_NO_TOKEN"}
        updated = 0
        for key, (a, ts_sym, tn, c) in cls.UNIVERSE.items():
            path = cls.bar_path(key)
            if not path.exists():
                continue
            try:
                r = requests.get(f"{base}/v3/marketdata/barcharts/{ts_sym}",
                                 params={"unit": "Daily", "barsback": recent_bars},
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                                 timeout=(5, 20))
                if r.status_code != 200:
                    _t.sleep(0.25); continue
                new = {}
                for b in (r.json() or {}).get("Bars", []) or []:
                    tsx = b.get("TimeStamp") or b.get("Timestamp")
                    try:
                        row = (str(tsx)[:10], float(b.get("Open")), float(b.get("High")), float(b.get("Low")),
                               float(b.get("Close")), int(float(b.get("TotalVolume") or b.get("Volume") or 0)))
                    except (TypeError, ValueError):
                        continue
                    if row[0] and row[4] > 0:
                        new[row[0]] = row
                if not new:
                    _t.sleep(0.25); continue
                existing = {}
                for rr in csv.reader(open(path)):
                    if rr and rr[0] != "date":
                        try:
                            existing[rr[0]] = (rr[0], float(rr[1]), float(rr[2]), float(rr[3]), float(rr[4]), int(float(rr[5])))
                        except (ValueError, IndexError):
                            pass
                existing.update(new)
                with open(path, "w", newline="") as f:
                    w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "volume"])
                    w.writerows(existing[d] for d in sorted(existing))
                updated += 1
            except Exception:
                pass
            _t.sleep(0.25)
        return {"status": "ALT_REFRESH_DONE", "updated": updated}
