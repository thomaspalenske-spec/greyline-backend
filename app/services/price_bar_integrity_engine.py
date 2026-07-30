"""Validate the actual PRICE BARS — the data every signal, ATR, stop and TP is computed from.

Nothing previously checked this. `data_integrity_engine` validates forecast/accuracy data;
the 557 daily price series were unchecked — which is exactly where a real corruption already
happened (one symbol's quote was written under every ticker, so every file "bottomed" at the
same 92-98 price). A signal computed on corrupt bars produces confident, completely fake edge.

CRITICAL (the data is WRONG — trading on it is unsafe):
  OHLC_VIOLATION          low > high, or low/high inconsistent with open/close
  DUPLICATE_CROSS_SYMBOL  the same exact close on the same date across many symbols — the
                          precise corruption signature this repo already suffered
  NONPOSITIVE             price <= 0 or negative volume

WARNING (unusual — needs eyes, not necessarily wrong):
  FROZEN_SERIES           identical close for N sessions running (dead/stale feed)
  SUSPICIOUS_JUMP         |move| past a threshold — usually an UNADJUSTED SPLIT, which would
                          silently corrupt ATR and make the doctrine's stop/TP nonsense
  STALE_FILE              last bar older than N days
  EMPTY_FILE              no usable rows

Cross-symbol duplicate detection is deliberately bounded to the recent window so memory stays
flat even in a full-history scan (per-symbol checks still cover everything in full mode).
"""

import csv
import json
from datetime import datetime
from pathlib import Path


class PriceBarIntegrityEngine:

    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/data_quality/price_bar_scan.json")

    RECENT_ROWS = 30          # rows per symbol in a fast scan (and the duplicate window)
    FROZEN_RUN = 5            # identical closes in a row before flagging
    JUMP_PCT = 40.0           # |daily move| >= this is usually an unadjusted split
    # Identical closes across symbols: corruption vs coincidence.
    #
    # The real incident was one symbol's quote written under EVERY ticker — dozens of files
    # sharing the same ~$92-98 close. A flat threshold of 4 caught that, but it was calibrated
    # on a 557-name large-cap universe. Expanding to ~1,800 names (including hundreds of $1-10
    # microcaps, and SPACs that sit at $10.00 BY CONSTRUCTION) made 4-symbol collisions a
    # statistical certainty: with 2-decimal ticks a $2 stock has only a few hundred plausible
    # closes, so coincidence is expected. It produced 62 false alarms and zero real findings.
    #
    # Discriminate on IMPROBABILITY instead: collisions are only surprising when the price is
    # high enough that the tick space is large, OR when so many symbols agree that no amount of
    # coincidence explains it.
    DUP_MIN_SYMBOLS = 4       # ...but only above DUP_MIN_PRICE, where collision is unlikely
    DUP_MIN_PRICE = 25.0      # below this, 2-decimal collisions happen by chance
    DUP_HARD_MIN_SYMBOLS = 15  # this many agreeing is corruption at ANY price level
    # $25-par PREFERRED stocks and baby bonds legitimately CLUSTER at par by design, so several of
    # them sharing a $25.xx close on the same day is NOT a cross-symbol copy error. Near a par value
    # require the HARD (15) threshold; away from par the 4-symbol rule stands. (Removed 8 false-positive
    # criticals that were all $25-par preferreds: AGNCL/BIPJ/BWNB/AQNB/... — 2026-07-30.)
    PAR_VALUES = (25.0, 50.0, 100.0, 1000.0)
    PAR_BAND = 2.0

    @classmethod
    def _near_par(cls, close):
        try:
            return any(abs(float(close) - p) <= cls.PAR_BAND for p in cls.PAR_VALUES)
        except (TypeError, ValueError):
            return False
    STALE_DAYS = 7

    CRITICAL_TYPES = ("OHLC_VIOLATION", "DUPLICATE_CROSS_SYMBOL", "NONPOSITIVE")

    def _read(self, path, limit=None):
        rows = []
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    try:
                        rows.append({
                            "date": str(r["date"])[:10],
                            "open": float(r["open"]), "high": float(r["high"]),
                            "low": float(r["low"]), "close": float(r["close"]),
                            "volume": float(r.get("volume") or 0),
                        })
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return []
        return rows[-limit:] if limit else rows

    def scan(self, full=False, save=True, max_issues=400):
        files = sorted(self.HIST_DIR.glob("*_daily.csv"))
        limit = None if full else self.RECENT_ROWS
        issues, rows_checked = [], 0
        dup_window = {}                       # date -> {close: [symbols]} (recent rows only)
        today = datetime.utcnow().date()

        for p in files:
            symbol = p.name.replace("_daily.csv", "")
            rows = self._read(p, limit)
            if not rows:
                issues.append({"symbol": symbol, "date": None, "type": "EMPTY_FILE",
                               "detail": "no usable rows"})
                continue
            rows_checked += len(rows)

            try:
                age = (today - datetime.fromisoformat(rows[-1]["date"]).date()).days
                if age > self.STALE_DAYS:
                    issues.append({"symbol": symbol, "date": rows[-1]["date"], "type": "STALE_FILE",
                                   "detail": f"last bar is {age} days old"})
            except Exception:
                pass

            frozen, prev_close = 0, None
            for r in rows:
                o, h, l, c, v = r["open"], r["high"], r["low"], r["close"], r["volume"]

                if min(o, h, l, c) <= 0 or v < 0:
                    issues.append({"symbol": symbol, "date": r["date"], "type": "NONPOSITIVE",
                                   "detail": f"o={o} h={h} l={l} c={c} v={v}"})
                if l > h or l > o or l > c or h < o or h < c:
                    issues.append({"symbol": symbol, "date": r["date"], "type": "OHLC_VIOLATION",
                                   "detail": f"o={o} h={h} l={l} c={c}"})

                if prev_close is not None and c == prev_close:
                    frozen += 1
                    if frozen == self.FROZEN_RUN:
                        issues.append({"symbol": symbol, "date": r["date"], "type": "FROZEN_SERIES",
                                       "detail": f"close {c} unchanged for {self.FROZEN_RUN}+ sessions"})
                else:
                    frozen = 0

                if prev_close and prev_close > 0:
                    move = (c / prev_close - 1) * 100
                    if abs(move) >= self.JUMP_PCT:
                        # Do NOT claim "split" — a full-history scan shows most of these are
                        # REAL events (AAPL -51.9% on 2000-09-29, AIG -60.8% in Sep 2008).
                        # Flag near-exact split ratios separately; everything else is just a
                        # large move to eyeball, not evidence of bad data.
                        ratio = c / prev_close
                        split_like = any(abs(ratio - r0) < 0.02
                                         for r0 in (0.5, 1/3, 0.25, 2/3, 0.75, 2.0, 3.0, 4.0))
                        issues.append({"symbol": symbol, "date": r["date"], "type": "LARGE_MOVE",
                                       "detail": f"{move:+.1f}% vs prior close"
                                                 + (" — near an exact split ratio, verify corporate action"
                                                    if split_like else " — verify (likely a real event)")})
                prev_close = c

            for r in rows[-self.RECENT_ROWS:]:
                dup_window.setdefault(r["date"], {}).setdefault(round(r["close"], 4), []).append(symbol)

        for date, by_close in dup_window.items():
            for close_val, syms in by_close.items():
                uniq = sorted(set(syms))
                if self._near_par(close_val):
                    # par clustering (preferreds/baby bonds) — only a mass agreement is corruption
                    improbable = len(uniq) >= self.DUP_HARD_MIN_SYMBOLS
                else:
                    improbable = (len(uniq) >= self.DUP_HARD_MIN_SYMBOLS
                                  or (len(uniq) >= self.DUP_MIN_SYMBOLS
                                      and float(close_val) >= self.DUP_MIN_PRICE))
                if improbable:
                    issues.append({"symbol": ", ".join(uniq[:8]) + ("…" if len(uniq) > 8 else ""),
                                   "date": date, "type": "DUPLICATE_CROSS_SYMBOL",
                                   "detail": f"{len(uniq)} symbols share the identical close {close_val}"})

        counts = {}
        for i in issues:
            counts[i["type"]] = counts.get(i["type"], 0) + 1
        critical = sum(counts.get(t, 0) for t in self.CRITICAL_TYPES)

        result = {
            "scanned_at": datetime.utcnow().isoformat(),
            "mode": "FULL_HISTORY" if full else f"RECENT_{self.RECENT_ROWS}_ROWS",
            "symbols_checked": len(files),
            "rows_checked": rows_checked,
            "counts": counts,
            "critical_count": critical,
            "warning_count": len(issues) - critical,
            "ok": critical == 0,
            "issues": issues[:max_issues],
            "issues_truncated": max(0, len(issues) - max_issues),
            "status": "PRICE_BARS_CLEAN" if critical == 0 else "PRICE_BARS_CORRUPTION_DETECTED",
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(result, indent=2))
            except Exception:
                pass
        return result

    def repair_ohlc(self, dry_run=True):
        """Fix physically impossible OHLC bars by clamping the low/high envelope.

        A bar is corrupt when low/high don't contain open and close. The repair is
        deterministic: low := min(o,h,l,c), high := max(o,h,l,c). OPEN AND CLOSE ARE NEVER
        ALTERED — they're the economically meaningful prices and what ATR/returns use; only
        the broken envelope is corrected to contain them.

        Safety: every other line is written back BYTE-IDENTICAL (no reformatting of the
        ~3.4M untouched rows), the original file is backed up before writing, and the exact
        before/after of each change is returned for audit.
        """
        backup_dir = Path("app/data/archive/price_bar_repairs")
        changes, files_changed = [], 0

        for p in sorted(self.HIST_DIR.glob("*_daily.csv")):
            symbol = p.name.replace("_daily.csv", "")
            try:
                lines = p.read_text().splitlines(keepends=True)
            except Exception:
                continue
            if len(lines) < 2:
                continue
            header = lines[0].strip().split(",")
            try:
                idx = {k: header.index(k) for k in ("date", "open", "high", "low", "close")}
            except ValueError:
                continue

            out, changed = [lines[0]], False
            for ln in lines[1:]:
                raw = ln.rstrip("\r\n")
                if not raw.strip():
                    out.append(ln)
                    continue
                parts = raw.split(",")
                try:
                    o = float(parts[idx["open"]]); h = float(parts[idx["high"]])
                    l = float(parts[idx["low"]]); c = float(parts[idx["close"]])
                except (ValueError, IndexError):
                    out.append(ln)
                    continue

                if l > h or l > o or l > c or h < o or h < c:
                    # Reuse the ORIGINAL strings for the new low/high so precision is
                    # preserved exactly — no float reformatting drift.
                    vals = {"open": (o, parts[idx["open"]]), "high": (h, parts[idx["high"]]),
                            "low": (l, parts[idx["low"]]), "close": (c, parts[idx["close"]])}
                    lo_s = min(vals.values(), key=lambda t: t[0])[1]
                    hi_s = max(vals.values(), key=lambda t: t[0])[1]
                    changes.append({"symbol": symbol, "date": parts[idx["date"]],
                                    "before": {"open": o, "high": h, "low": l, "close": c},
                                    "after": {"open": o, "high": float(hi_s),
                                              "low": float(lo_s), "close": c}})
                    parts[idx["low"]], parts[idx["high"]] = lo_s, hi_s
                    out.append(",".join(parts) + "\n")
                    changed = True
                else:
                    out.append(ln)

            if changed:
                files_changed += 1
                if not dry_run:
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    (backup_dir / p.name).write_text("".join(lines))
                    p.write_text("".join(out))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "dry_run": dry_run,
            "files_changed": files_changed,
            "bars_repaired": len(changes),
            "changes": changes,
            "backup_dir": str(backup_dir) if not dry_run else None,
            "status": "PRICE_BAR_REPAIR_PREVIEW" if dry_run else "PRICE_BAR_REPAIR_APPLIED",
        }

    SCAN_INTERVAL_HOURS = 24

    def scan_if_due(self, hours=None, full=True):
        """Run a FULL scan only when the saved one has gone stale.

        Self-gating so the scheduler can call this every cycle while the actual 3.4M-row scan
        (several seconds of I/O) runs at most once a day — right after the daily bars land.
        Keeps the Reality Guard backed by full-history coverage instead of a 30-row window.
        """
        # Explicit None check — `hours or DEFAULT` would silently turn hours=0 ("scan now")
        # into the 24h default, making a forced rescan impossible.
        hours = self.SCAN_INTERVAL_HOURS if hours is None else float(hours)
        prev = self.last_scan()
        if prev:
            try:
                age_h = (datetime.utcnow()
                         - datetime.fromisoformat(prev["scanned_at"])).total_seconds() / 3600.0
                if age_h < hours:
                    return {"status": "PRICE_BAR_SCAN_NOT_DUE", "ran": False,
                            "hours_since_last": round(age_h, 2),
                            "last_status": prev.get("status"),
                            "last_critical": prev.get("critical_count")}
            except Exception:
                pass
        result = self.scan(full=full, save=True)
        result["ran"] = True
        return result

    def last_scan(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
