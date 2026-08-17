"""Make the universe survivorship-free FROM NOW ON, and be explicit that history is not.

GreyLine's 557 symbols are today's index membership applied backwards. Every company that
failed is simply absent: ENRN, LEH, BSC, WCOM, and — recently enough to matter — SIVB and FRC,
both S&P 500 members that went to zero in 2023. Every backtest silently assumed it would never
have held either. That bias flatters results in one direction, always.

The historical half is UNFIXABLE with what we have. TradeStation returns "Invalid Symbol" for
every delisted ticker tested (SIVB, FRC, LEH, BSC, ENRN, WCOM, TWTR, ATVI, VMW, SGEN), so
dead-company prices cannot be recovered at any effort. Only a survivorship-free vendor fixes
that, and it costs money.

The FORWARD half is free, and this engine owns it. The insight is that the price files live on
OUR disk — a name only vanishes from the dataset if we let it. So:

  1. POINT-IN-TIME MEMBERSHIP  Append today's universe to a dated, append-only archive. A
     backtest can then ask "who was tradable on 2027-03-14?" instead of assuming today's list.
  2. NEVER DELETE             A symbol that leaves the index keeps its CSV and is recorded in
     a delisted registry with its last observed bar. That is precisely the data a vendor
     would charge for — we simply stop discarding it.
  3. DECLARE THE BIAS         Expose `survivorship_free_from`, so any study can state whether
     its window is clean or biased instead of leaving the reader to assume.

Point 3 matters as much as the others. The danger is not that the bias exists — it is that a
future hypothesis shows promise and nobody can tell whether it is real or an artifact of a
universe rigged to contain only winners.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path


class UniverseSurvivorshipEngine:

    HIST_DIR = Path("app/data/historical")
    ARCHIVE = Path("app/data/research/universe_pit/membership.jsonl")
    DELISTED = Path("app/data/research/universe_pit/delisted_registry.json")

    STALE_DAYS = 10           # no new bar in this long -> the feed has stopped carrying it

    def _current_symbols(self):
        return sorted(p.name.replace("_daily.csv", "")
                      for p in self.HIST_DIR.glob("*_daily.csv"))

    def _last_bar_date(self, symbol):
        p = self.HIST_DIR / f"{symbol}_daily.csv"
        try:
            lines = p.read_text().splitlines()
        except Exception:
            return None
        for ln in reversed(lines[1:]):
            if ln.strip():
                return ln.split(",")[0][:10]
        return None

    def _read_archive(self):
        out = []
        try:
            for ln in self.ARCHIVE.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            return []
        return out

    def snapshot(self, save=True):
        """Append today's membership to the point-in-time archive (one record per day)."""
        symbols = self._current_symbols()
        today = datetime.utcnow().date().isoformat()
        digest = hashlib.sha256(",".join(symbols).encode()).hexdigest()[:16]

        archive = self._read_archive()
        if archive and archive[-1].get("date") == today:
            return {"status": "PIT_SNAPSHOT_ALREADY_TAKEN_TODAY", "date": today,
                    "symbols": len(symbols), "archive_days": len(archive)}

        changed = None
        if archive:
            prev = set(archive[-1].get("symbols") or [])
            now = set(symbols)
            changed = {"added": sorted(now - prev), "removed": sorted(prev - now)}

        record = {"date": today, "count": len(symbols), "hash": digest, "symbols": symbols}
        if save:
            try:
                self.ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
                with open(self.ARCHIVE, "a") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                return {"status": "PIT_SNAPSHOT_WRITE_FAILED", "error": str(e)[:120]}

        return {"status": "PIT_SNAPSHOT_RECORDED", "date": today, "symbols": len(symbols),
                "hash": digest, "archive_days": len(archive) + 1, "membership_change": changed}

    def detect_departures(self, save=True):
        """Find symbols whose feed has gone quiet and record them INSTEAD of dropping them.

        A delisting is exactly the observation a survivorship-free dataset is made of. The
        CSV is retained untouched; only the registry is written. Nothing here deletes.
        """
        cutoff = (datetime.utcnow().date() - timedelta(days=self.STALE_DAYS)).isoformat()
        try:
            registry = json.loads(self.DELISTED.read_text())
        except Exception:
            registry = {}

        newly = []
        for sym in self._current_symbols():
            last = self._last_bar_date(sym)
            if not last or last >= cutoff:
                continue
            if sym in registry:
                continue
            registry[sym] = {
                "last_bar_date": last,
                "detected_at": datetime.utcnow().isoformat(),
                "note": "feed stopped updating — delisted, renamed, or acquired. "
                        "CSV RETAINED so this name stays in future point-in-time studies.",
            }
            newly.append(sym)

        if save and newly:
            try:
                self.DELISTED.parent.mkdir(parents=True, exist_ok=True)
                self.DELISTED.write_text(json.dumps(registry, indent=2))
            except Exception as e:
                return {"status": "DELISTED_REGISTRY_WRITE_FAILED", "error": str(e)[:120]}

        return {"status": "DEPARTURE_SCAN_COMPLETE", "newly_recorded": newly,
                "registry_size": len(registry), "stale_cutoff": cutoff}

    def status(self):
        """Honest statement of what is and is not survivorship-free."""
        archive = self._read_archive()
        try:
            registry = json.loads(self.DELISTED.read_text())
        except Exception:
            registry = {}

        free_from = archive[0]["date"] if archive else None
        # Quantified magnitude of the ALREADY-BAKED-IN historical bias (best-effort).
        bias = None
        try:
            from app.services.survivorship_bias_engine import SurvivorshipBiasEngine
            bias = SurvivorshipBiasEngine().headline()
        except Exception:
            bias = None
        return {
            "historical_bias_magnitude": bias,
            "timestamp": datetime.utcnow().isoformat(),
            "archive_days": len(archive),
            "survivorship_free_from": free_from,
            "retained_delisted_symbols": sorted(registry),
            "retained_delisted_count": len(registry),
            "history_is_survivorship_biased": True,   # and will stay true for the pre-archive era
            "detail": (
                f"Point-in-time membership recorded from {free_from}. Data BEFORE that date is "
                "today's index membership applied backwards and excludes every company that "
                "failed (SIVB and FRC among them) — studies on it are biased upward. "
                "Delisted-company prices cannot be recovered from TradeStation, which returns "
                "'Invalid Symbol' for them; only a survivorship-free vendor fixes the past."
                if free_from else
                "No point-in-time archive yet — the entire dataset is survivorship-biased."
            ),
        }

    def study_exposure(self, universe, since=None, index_level=False):
        """QUANTIFY the survivorship exposure of ONE backtest, so a study can cite a number instead of a
        blanket "any positive result is an upper bound" caveat.

        `index_level=True` (VIX / index / single-ETF series like the 24yr index-VRP backtest) is
        survivorship-free BY CONSTRUCTION — an index level does not drop failed members from its own past.
        For a single-name universe, the exposure is: (a) how many of its names are already in the delisted
        registry (post-archive, forward-only — small today), and (b) whether the study window reaches BEFORE
        the PIT archive began (survivorship_free_from), where today's survivors are applied backward and the
        pre-archive failures are unrecoverable and ABSENT — the real, irreducible upward bias."""
        names = sorted({str(n).upper() for n in (universe or []) if n})
        if index_level:
            return {"status": "SURVIVORSHIP_EXPOSURE", "index_level": True, "clean": True,
                    "names": len(names),
                    "note": ("index / single-ETF level series are survivorship-free BY CONSTRUCTION — the "
                             "level does not exclude failed constituents from its own history; no bias.")}
        try:
            registry = set(json.loads(self.DELISTED.read_text()))
        except Exception:
            registry = set()
        archive = self._read_archive()
        free_from = archive[0]["date"] if archive else None
        delisted_in_uni = sorted(n for n in names if n in registry)
        # the study reaches into the biased (pre-archive) era if its start precedes the archive
        reaches_pre_archive = bool(since and free_from and str(since)[:10] < str(free_from)[:10]) or \
            (bool(free_from) and not since)
        return {
            "status": "SURVIVORSHIP_EXPOSURE",
            "index_level": False,
            "names": len(names),
            "survivorship_free_from": free_from,
            "study_since": str(since)[:10] if since else None,
            "reaches_pre_archive_biased_era": reaches_pre_archive,
            "delisted_names_in_universe": delisted_in_uni,     # post-archive, registry-tracked (forward-only)
            "delisted_count_in_universe": len(delisted_in_uni),
            "bias_direction": "upward" if reaches_pre_archive else "none_observed",
            "note": (
                ("Study window reaches BEFORE the PIT archive (%s): its single-name universe is today's "
                 "SURVIVORS applied backward — every name that failed before the archive is unrecoverable "
                 "(TradeStation returns 'Invalid Symbol') and ABSENT, so the result is an UPPER BOUND. "
                 "%d of its names have delisted since the archive began (registry-tracked)."
                 % (free_from, len(delisted_in_uni))) if reaches_pre_archive else
                ("Study window is within the PIT-archived era (from %s): survivorship-clean for this window; "
                 "%d registry delistings among its names." % (free_from, len(delisted_in_uni)))
                if free_from else
                "No PIT archive yet — treat any single-name study as survivorship-biased upward."),
        }

    def membership_on(self, date):
        """Universe as recorded on/just before `date` — None if it predates the archive.

        Returning None rather than today's list is deliberate: silently substituting current
        membership for a date we have no record of is the bias itself.
        """
        best = None
        for rec in self._read_archive():
            if rec.get("date") <= date:
                best = rec
            else:
                break
        return best["symbols"] if best else None
