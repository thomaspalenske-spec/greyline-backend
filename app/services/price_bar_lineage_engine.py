"""Detect SILENT retroactive changes to settled price history — the reproducibility guarantee.

Every other data check verifies the bars are correct RIGHT NOW. None of them notices when a
bar that was already settled quietly changes underneath you. The CSVs are mutable: the nightly
refresh rewrites them, and data vendors silently revise history (restatements, re-adjustments,
backfill corrections). When that happens, nothing breaks and nothing warns — the file stays
internally consistent and still matches the vendor's NEW value, so `PRICE_BARS_MATCH_SOURCE`
still passes. The validated history changed and the guard stays green.

That silence is a reproducibility hole. The mechanical-flow study returned specific numbers;
re-run it next month and you cannot tell whether a different result is new data or REVISED
data. The four OHLC bars repaired earlier could revert and no one would know.

THE MECHANISM: fingerprint each symbol's SETTLED segment (bars older than a few days, which
should be frozen) and store the hashes. On each run, recompute the fingerprint OVER THE SAME
DATE RANGE the baseline covered and compare. A settled bar that changed flips the hash.

  * Comparing the fixed baseline range — not "everything older than 5 days today" — is what
    stops newly-settled bars from false-alarming every single day. The frontier only advances
    when the baseline is deliberately re-accepted.
  * Hashing is per (symbol, year), so a change localizes to a symbol-year rather than just
    "something moved". A split re-adjustment touches every year (legitimate, worth seeing); a
    single corrupted or restated bar touches one.
  * The fingerprint is over NORMALISED tuples (date, o, h, l, c, v), so reformatting or
    whitespace never trips it — only an economically meaningful change does.

A detected change is NOT automatically corruption. It is one of: a legitimate vendor
restatement, a retroactive split/dividend re-adjustment, or genuine corruption. The engine's
job is to make the change VISIBLE and localized so it can be judged, then re-accepted as the
new baseline once understood. Invisible is the only unacceptable state.
"""

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path


class PriceBarLineageEngine:

    HIST_DIR = Path("app/data/historical")
    ALT_DIR = Path("app/data/alt_assets")          # futures/FX bars (added 2026-08-12) — also guard these
    MANIFEST = Path("app/data/data_quality/price_bar_lineage_manifest.json")
    REPORT = Path("app/data/data_quality/price_bar_lineage_report.json")

    @classmethod
    def _bar_files(cls):
        """(manifest_key, path) over BOTH bar stores. Historical keys stay BARE (backward-compatible with
        an existing baseline); alt_assets keys are prefixed 'alt_assets/' so a symbol that exists in both
        stores (e.g. C = Citigroup vs corn @C) can't collide in the manifest."""
        out = [(p.name.replace("_daily.csv", ""), p) for p in sorted(cls.HIST_DIR.glob("*_daily.csv"))]
        out += [("alt_assets/" + p.name.replace("_daily.csv", ""), p)
                for p in sorted(cls.ALT_DIR.glob("*_daily.csv"))]
        return out

    SETTLED_LAG_DAYS = 5          # bars at least this old are "settled" and must not change
    VERIFY_INTERVAL_HOURS = 24

    # ---------------------------------------------------------------- read

    def _settled_rows(self, path, through):
        """Normalised (date, o, h, l, c, v) tuples with date <= `through`, oldest first."""
        rows = []
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    try:
                        d = str(r["date"])[:10]
                        if d > through:
                            continue
                        rows.append((d,
                                     round(float(r["open"]), 6), round(float(r["high"]), 6),
                                     round(float(r["low"]), 6), round(float(r["close"]), 6),
                                     round(float(r.get("volume") or 0), 2)))
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return []
        rows.sort()
        return rows

    @staticmethod
    def _hash(rows):
        h = hashlib.sha256()
        for t in rows:
            h.update(("|".join(map(str, t)) + "\n").encode())
        return h.hexdigest()

    def _year_hashes(self, rows):
        by_year = {}
        order = {}
        for t in rows:
            by_year.setdefault(t[0][:4], []).append(t)
        return {y: self._hash(v) for y, v in by_year.items()}

    def _fingerprint(self, path, through):
        rows = self._settled_rows(path, through)
        if not rows:
            return None
        return {
            "settled_hash": self._hash(rows),
            "settled_bars": len(rows),
            "first_date": rows[0][0],
            "last_settled_date": rows[-1][0],
            "year_hashes": self._year_hashes(rows),
        }

    # ------------------------------------------------------------ baseline

    def snapshot(self, force=False):
        """Establish (or deliberately re-accept) the lineage baseline.

        First run bootstraps it. After that, only an explicit force=True re-baselines —
        because silently re-accepting a change is exactly the invisibility this prevents.
        """
        if self.MANIFEST.exists() and not force:
            return {"status": "LINEAGE_BASELINE_EXISTS", "created": False,
                    "detail": "baseline already set; pass force=true to re-accept after review"}

        through = (datetime.utcnow().date() - timedelta(days=self.SETTLED_LAG_DAYS)).isoformat()
        symbols = {}
        for key, p in self._bar_files():
            fp = self._fingerprint(p, through)
            if fp:
                symbols[key] = fp

        manifest = {
            "created_at": datetime.utcnow().isoformat(),
            "settled_lag_days": self.SETTLED_LAG_DAYS,
            "settled_through": through,
            "symbol_count": len(symbols),
            "symbols": symbols,
        }
        try:
            self.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            self.MANIFEST.write_text(json.dumps(manifest))
        except Exception as e:
            return {"status": "LINEAGE_BASELINE_WRITE_FAILED", "error": str(e)[:120]}
        return {"status": "LINEAGE_BASELINE_RECORDED", "created": True,
                "settled_through": through, "symbols": len(symbols)}

    # -------------------------------------------------------------- verify

    def verify(self, save=True):
        """Recompute over the baseline's date range and report anything that changed."""
        try:
            manifest = json.loads(self.MANIFEST.read_text())
        except Exception:
            return {"status": "LINEAGE_NO_BASELINE", "ok": None,
                    "detail": "no baseline yet — call snapshot() first"}

        through = manifest["settled_through"]
        base = manifest.get("symbols") or {}
        current_files = {key: p for key, p in self._bar_files()}

        changed, removed = [], []
        for sym, prior in base.items():
            path = current_files.get(sym)
            if path is None:
                removed.append({"symbol": sym, "last_settled_date": prior.get("last_settled_date")})
                continue
            now = self._fingerprint(path, through)
            if now is None:
                removed.append({"symbol": sym, "note": "settled rows no longer readable"})
                continue
            if now["settled_hash"] != prior["settled_hash"]:
                # localise: which calendar years' fingerprints differ
                py, ny = prior.get("year_hashes", {}), now["year_hashes"]
                diff_years = sorted(y for y in set(py) | set(ny) if py.get(y) != ny.get(y))
                changed.append({
                    "symbol": sym,
                    "years_changed": diff_years,
                    "years_changed_count": len(diff_years),
                    "bars_before": prior["settled_bars"],
                    "bars_after": now["settled_bars"],
                    "bar_count_delta": now["settled_bars"] - prior["settled_bars"],
                    # a change spanning most years is likely a retroactive re-adjustment
                    # (split/dividend); one or a few years is a targeted restatement/corruption
                    "likely": ("RETROACTIVE_READJUSTMENT" if len(diff_years) >= max(2, int(len(ny) * 0.6))
                               else "TARGETED_RESTATEMENT_OR_CORRUPTION"),
                })

        new_syms = sorted(set(current_files) - set(base))
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "baseline_created_at": manifest.get("created_at"),
            "settled_through": through,
            "symbols_checked": len(base),
            "unchanged": len(base) - len(changed) - len(removed),
            "changed_count": len(changed),
            "changed": sorted(changed, key=lambda c: -c["years_changed_count"])[:50],
            "removed_count": len(removed),
            "removed": removed[:50],
            "new_symbols": new_syms[:50],
            "new_symbol_count": len(new_syms),
            "ok": len(changed) == 0,
            "status": ("LINEAGE_STABLE" if not changed
                       else "SETTLED_HISTORY_CHANGED_SINCE_BASELINE"),
        }
        if save:
            try:
                self.REPORT.parent.mkdir(parents=True, exist_ok=True)
                self.REPORT.write_text(json.dumps(result, indent=2))
            except Exception:
                pass
        return result

    def verify_if_due(self, hours=None):
        """Self-gating: bootstrap the baseline if absent, else verify at most once/interval."""
        if not self.MANIFEST.exists():
            snap = self.snapshot()
            snap["ran"] = True
            return snap
        # explicit None check so hours=0 ("verify now") isn't swallowed by `or DEFAULT`
        hours = self.VERIFY_INTERVAL_HOURS if hours is None else float(hours)
        prev = self.last_report()
        if prev:
            try:
                age_h = (datetime.utcnow()
                         - datetime.fromisoformat(prev["timestamp"])).total_seconds() / 3600.0
                if age_h < hours:
                    return {"status": "LINEAGE_VERIFY_NOT_DUE", "ran": False,
                            "hours_since_last": round(age_h, 2),
                            "last_status": prev.get("status"),
                            "last_changed": prev.get("changed_count")}
            except Exception:
                pass
        res = self.verify(save=True)
        res["ran"] = True
        return res

    def last_report(self):
        try:
            return json.loads(self.REPORT.read_text())
        except Exception:
            return None

    def baseline_info(self):
        try:
            m = json.loads(self.MANIFEST.read_text())
            return {"created_at": m.get("created_at"), "settled_through": m.get("settled_through"),
                    "symbols": m.get("symbol_count"), "settled_lag_days": m.get("settled_lag_days")}
        except Exception:
            return None
